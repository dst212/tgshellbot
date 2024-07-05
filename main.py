#!/usr/bin/env python3
if __name__ == "__main__":
    from keys import TOKEN, API_ID, API_HASH
    from config import BOTNAME, ADMINS, LOG_CHAT

    from misc import commands
    from misc.sudo import SudoConfig

    import uvloop

    from pyrogram import Client, idle
    from pyrogram.enums import ParseMode
else:
    BOTNAME = None

from job import Job
from misc.fun import format_chat, quick_answer, query_match

import asyncio
import html
import logging
import signal


from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.types import (
    Message, User,
    InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton,
)


def init(bot, sudo):
    jobs = {}

    def get_job(chat_id, message_id, from_user_id):
        if jobs.get(chat_id):
            job = jobs[chat_id].get(message_id)
            if job and job.from_user.id == from_user_id:
                return job
        return None

    async def run(command: str, user: User, m: Message):
        # Cache the job
        if not jobs.get(m.chat.id):
            jobs[m.chat.id] = {}
        job = jobs[m.chat.id][m.id] = Job(command=command, message=m, from_user=user)
        await job.run()
        del jobs[m.chat.id][m.id]

    @bot.on_message(filters.command("start"))
    async def _(bot, m):
        if m.from_user.id in ADMINS:
            await m.reply("At your service. Send a message to run a command.")
        else:
            await sudo.log(f"{format_chat(m.from_user)} started the bot.")

    # List running commands
    @bot.on_message(filters.command("list"))
    async def _(bot, m):
        if m.from_user.id in ADMINS:
            out = ""
            for chat, cjobs in jobs.items():
                if cjobs:
                    out += (
                        f"<b>From {format_chat(await bot.get_chat(chat))}:</b>\n" +
                        "\n".join(
                            f"[<code>{job.pid}</code>] <code>{html.escape(job.command)}</code>"
                            for job in cjobs.values()
                        ) + "\n\n"
                    )
            await m.reply(out or "No command is running.")

    # Send signals to a process
    @bot.on_message(filters.command(["kill", "sig"]))
    async def _(bot, m):
        if m.from_user.id in ADMINS:
            if m.reply_to_message_id and m.reply_to_message.outgoing:
                job = get_job(m.chat.id, m.reply_to_message_id, (m.from_user or m.sender_chat).id)
                if isinstance(job, Job):
                    try:
                        sig = (
                            int(m.command[1]) if m.command[1].isnumeric() else
                            signal.Signals[m.command[1]].value
                        )
                    except (KeyError, IndexError):
                        sig = signal.SIGKILL.value
                    job.send_signal(sig)
                    await m.reply(
                        f"Sent signal <code>{sig}</code> to <code>{job.pid}</code>.",
                        quote=True,
                    )
                else:
                    await m.reply("Reply to a running command.")
            else:
                await m.reply("Reply to the root message of the command that should receive the signal.")

    @bot.on_callback_query(filters.regex(r"^sig (-|)[0-9]+$"))
    async def _(bot, c):
        if c.from_user.id not in ADMINS:
            return
        m = c.message
        if m:
            sig = int(c.data[c.data.find(" ") + 1:])
            job = get_job(m.chat.id, m.id, c.from_user.id)
            if isinstance(job, Job):
                job.send_signal(sig)
                await c.answer(f"Sent signal {sig} to process {job.pid}.")
            else:
                await c.answer("Couldn't retrieve the process.", show_alert=True)
        else:
            await c.answer("Couldn't retrieve the message.", show_alert=True)

    # Buttons having an url
    async def _func(_, __, message):
        rm = message.reply_markup
        return isinstance(rm, InlineKeyboardMarkup) and rm.inline_keyboard[0][0].url
    has_url_button = filters.create(_func)

    # Run a command
    @bot.on_message(
        (filters.private & filters.text & ~filters.reply & ~has_url_button) | filters.command("run"))
    async def _(bot, m):
        cmd = " ".join(m.command[1:]) if m.command else m.text
        # TODO: make an actual parser
        cmd = f"{cmd[:4]} -S {cmd[5:]}" if cmd.startswith("sudo ") else cmd
        if m.from_user.id in ADMINS:
            if cmd:
                await run(cmd, m.from_user, await m.reply("Loading..."))
            else:
                await m.reply("I'm already running, donkey.")
        else:
            await m.reply("You are not whitelisted. This incident will be reported.")
            await sudo.log(
                f"{format_chat(m.from_user)} tried to run the following command:\n"
                f"<pre language=\"shell\">{html.escape(cmd)}</pre>"
            )

    # Write to stdin
    @bot.on_message(filters.text & filters.reply & ~has_url_button)
    async def _(bot, m):
        if m.reply_to_message.outgoing and m.from_user.id in ADMINS:
            job = get_job(m.chat.id, m.reply_to_message_id, (m.from_user or m.sender_chat).id)
            if isinstance(job, Job):
                await job.write(m.text)
            else:
                if m.chat.type == ChatType.PRIVATE:
                    await m.reply("Do not reply to older messages when sending commands.")

    # Send sensitive input
    @bot.on_inline_query(filters.regex(r"^type (-|)[0-9]+ [0-9]+"))
    async def _(bot, q):
        if q.from_user.id in ADMINS:
            args = q.query.split(" ", 4)
            job = get_job(int(args[1]), int(args[2]), q.from_user.id)
            if isinstance(job, Job):
                await q.answer([InlineQueryResultArticle(
                    "Send input.",
                    InputTextMessageContent("The essential is invisible to the eyes."),
                    description=args[3] if len(args) > 3 else "[new line]",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🆗", url="https://www.youtube.com/watch?v=xvFZjo5PgG0")]])
                )])
            else:
                await quick_answer(q, "Process not found.", "f")

    # Receive sensitive input
    @bot.on_chosen_inline_result(query_match(r"^type (-|)[0-9]+ [0-9]+"))
    async def _(bot, r):
        args = r.query.split(" ", 4)
        job = get_job(int(args[1]), int(args[2]), r.from_user.id)
        if isinstance(job, Job):
            await job.write(args[3] if len(args) > 3 else "", secret=True)


if __name__ == "__main__":
    logging.basicConfig(
        format="[%(asctime)s|%(levelname)s] - %(name)s - %(message)s", level=logging.INFO)
    log = logging.getLogger(BOTNAME)

    async def main():
        bot = Client(BOTNAME, api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN)
        bot.set_parse_mode(ParseMode.HTML)

        sudo = SudoConfig(
            bot,
            admins=ADMINS,
            log_chat=LOG_CHAT,
            prefix=".",
            error_message="An error occurred.",
        )
        commands.init("id", bot)
        commands.init("ping", bot)
        commands.init("inspect", bot)

        init(bot, sudo)

        async with bot:
            log.info("Started.")
            await sudo.log("Bot started.")
            await idle()
            await sudo.log("Bot stopped.")
            log.info("Stopped.")

    uvloop.install()
    asyncio.run(main())
