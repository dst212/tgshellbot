from misc.fun import try_wait

import asyncio
import html
import time
import signal
import traceback
import logging

from pyrogram.types import Message, User, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified


log = logging.getLogger(__name__)

# Maximum output length to fit in the output message
# A deviation of 256 ensures the spaces for the command and the pid,
# I could optimize it but I won't
MAX_LENGTH = 4096 - 256


class Job:
    _buf: bytes = b""
    _proc = None
    _short: str = None
    _header: str = None
    _markup: InlineKeyboardMarkup = None
    _time: float = None

    def __init__(self, command: str, from_user: User, message: Message):
        self._command = command
        self._from_user = from_user
        self._top_message = message
        self._message = message
        self._olock = asyncio.Lock()
        self._elock = asyncio.Lock()
        self._buf_lock = asyncio.Lock()

    @property
    def command(self):
        return self._command

    @property
    def short_command(self):
        if self._short is None:
            self._short = (
                self._command if len(self._command) < 80 else
                self._command[:self._command.find(" ")]
            )
        return self._short

    @property
    def from_user(self):
        return self._from_user

    @property
    def message(self):
        return self._message

    @property
    def proc(self):
        return self._proc

    @property
    def pid(self):
        return str(self._proc.pid) if self._proc else "---"

    @property
    def running(self):
        return self._proc and self._proc.returncode is None

    @property
    def name(self):
        return f"{self._message.chat.id}/{self._message.id}"

    @property
    def header(self):
        if self._header is None:
            self._header = f"[<code>{self.pid}</code>] <code>{html.escape(self.short_command)}</code>"
        return self._header

    @property
    def markup(self):
        if self._markup is None:
            self._markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("❌ SIGKILL", callback_data=f"sig {signal.SIGKILL.value}"),
                    InlineKeyboardButton("🛑 SIGTERM", callback_data=f"sig {signal.SIGTERM.value}"),
                ],
                [InlineKeyboardButton(
                    "#️⃣ Send secret input",
                    switch_inline_query_current_chat=f"type {self._message.chat.id} {self._top_message.id} ",
                )],
            ])
        return self._markup

    # Write to stdin
    async def write(self, string: str, secret: bool = False):
        self._proc.stdin.write(bytes(f"{string}\n", "utf-8"))
        await self._proc.stdin.drain()
        log_str = "[secret]" if secret else f"\"{string}\""
        log.info(f"~[{self.pid}] {self.short_command} << {log_str}")

    def send_signal(self, signal):
        return self._proc.send_signal(signal)

    # Append output to the buffer using a Lock
    async def buf_append(self, buf: bytes):
        async with self._buf_lock:
            self._buf += buf

    # Edit and ignore MessageNotModified
    async def _edit(self, *args, **kwargs):
        try:
            await self._message.edit(*args, **kwargs)
        except MessageNotModified:
            pass

    # Refresh the output message
    async def flush(self):
        async with self._buf_lock:
            # Handle max length (4096 bytes)
            while len(self._buf) > MAX_LENGTH:
                await try_wait(
                    self._edit,
                    f"{self.header}\n\n"
                    "Output:\n<pre language=\"log\">"
                    f"{html.escape(self._buf[:MAX_LENGTH].decode())}%</pre>\n"
                )
                self._buf = b"%" + self._buf[MAX_LENGTH:]
                self._message = await try_wait(self._message.reply, "Loading...", quote=True)
            # Update the output message
            await try_wait(
                self._edit,
                f"{self.header}\n\n"
                f"Output:\n<pre language=\"log\">{html.escape(self._buf.decode() or '%')}</pre>\n" +
                ("Running..." if self._time is None else
                 f"Exited with code <code>{self._proc.returncode}</code> in {self._time}s."),
                reply_markup=self.markup if self.running else None,
            )

    # Thread's target to log stdout and update the Telegram message
    async def _log(self):
        async with self._olock:
            while True:
                buf = await self._proc.stdout.readline()
                if not buf:
                    break
                await self.buf_append(buf)
                if self.running:
                    # The buffer is flushed only when the program is running, otherwise it's run()'s task.
                    # I could read all bytes above here and flush all at once, but then stdout and stderr
                    # would print their statements in different order, so I'll keep the readline() method
                    # and buf_append() for each line from both stdout and stderr
                    try:
                        await self.flush()
                    except Exception:
                        log.error(f"Error while flushing {self.name}/stdout ({self.command}):")
                        traceback.print_exc()

    # Same as _log() but with stderr
    async def _logerr(self):
        async with self._elock:
            while True:
                buf = await self._proc.stderr.readline()
                if not buf:
                    break
                await self.buf_append(buf)
                if self.running:
                    try:
                        await self.flush()
                    except Exception:
                        log.error(f"Error while flushing {self.name}/stderr ({self.command}):")
                        traceback.print_exc()

    # Run the command
    async def run(self):
        loop = asyncio.get_event_loop()
        start = time.time()
        self._proc = await asyncio.create_subprocess_shell(
            self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info(f"+[{self.pid}] {self.short_command}")

        # Update output message with PID and buttons
        asyncio.run_coroutine_threadsafe(self.flush(), loop)
        # Start logging stdout and stderr
        asyncio.run_coroutine_threadsafe(self._log(), loop)
        asyncio.run_coroutine_threadsafe(self._logerr(), loop)
        await self._proc.wait()

        self._time = round((time.time() - start) * 1000)/1000
        log.info(f"×[{self.pid}] {self.short_command} ({self._proc.returncode})")
        # Flush at once what's left
        await self._elock.acquire()
        await self._olock.acquire()
        try:
            await self.flush()
        finally:
            self._elock.release()
            self._olock.release()
        # Let's put this here to notify users when a process stops
        await self._message.reply(
            f"Process exited with code <code>{self._proc.returncode}</code>.\n"
            f"Execution time: {self._time}s.",
            quote=True,
        )
