"""
"By Muhammad" kanali uchun rasmiy bot.

Imkoniyatlar:
  • Foydalanuvchi adminga xabar yozadi, admin "Reply" qilib javob beradi.
  • Har bir foydalanuvchiga shaxsiy referal havola.
  • Havola orqali target() ta odam qo'shilsa -> yopiq kanalga bir martalik taklif havolasi.
  • Har kuni belgilangan vaqtda asosiy kanalga eng ko'p odam qo'shganlar reytingi.
"""

import asyncio
import html
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ChatMemberUpdated,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

load_dotenv()

# ───────────────────────── Sozlamalar ─────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])                       # sizning Telegram ID
TOP_COUNT = int(os.getenv("TOP_COUNT", "10"))
DB_PATH = os.getenv("DB_PATH", "bot.db")

TZ = timezone(timedelta(hours=5))  # Asia/Tashkent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

# ───────────────────────── Ma'lumotlar bazasi ─────────────────────────
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id      INTEGER PRIMARY KEY,
        full_name    TEXT,
        username     TEXT,
        referred_by  INTEGER,
        counted      INTEGER DEFAULT 0,   -- referal sifatida hisoblanganmi
        ref_count    INTEGER DEFAULT 0,
        rewarded     INTEGER DEFAULT 0,   -- yopiq kanal havolasi berilganmi
        invite_link  TEXT,
        joined_at    TEXT
    );
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS ref_links (
        user_id INTEGER,
        channel TEXT,
        link    TEXT,
        PRIMARY KEY (user_id, channel)
    );
    CREATE TABLE IF NOT EXISTS joins (
        joiner_id   INTEGER PRIMARY KEY,
        referrer_id INTEGER,
        joined_at   TEXT
    );
    CREATE TABLE IF NOT EXISTS support (
        admin_msg_id INTEGER PRIMARY KEY,
        user_id      INTEGER
    );
    """
)
db.commit()


# Sozlamalar bot ichida /sozlama orqali o'zgartiriladi (.env dagisi — boshlang'ich qiymat)
DEFAULTS = {
    "main_channel": os.getenv("MAIN_CHANNEL", ""),         # @bymuhammad
    "main_url": os.getenv("MAIN_URL", ""),                 # kanalga obuna havolasi
    "private_channel": os.getenv("PRIVATE_CHANNEL_ID", ""),  # -100...
    "target": os.getenv("REF_TARGET", "5"),
    "top_time": os.getenv("TOP_TIME", "20:00"),
}


def cfg(key: str) -> str:
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULTS.get(key, "")


def set_cfg(key: str, value: str):
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
    db.commit()


def main_channel():
    return cfg("main_channel")


def main_url():
    return cfg("main_url") or f"https://t.me/{main_channel().lstrip('@')}"


def private_channel():
    v = cfg("private_channel")
    return int(v) if v.lstrip("-").isdigit() else None


def target() -> int:
    return int(cfg("target"))


def top_time() -> str:
    return cfg("top_time")


def get_user(user_id: int):
    return db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


# ───────────────────────── Klaviaturalar ─────────────────────────
BTN_REF = "🔗 Referal havolam"
BTN_STAT = "📊 Natijam"
BTN_TOP = "🏆 Reyting"
BTN_ADMIN = "✉️ Adminga yozish"

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_REF), KeyboardButton(text=BTN_STAT)],
        [KeyboardButton(text=BTN_TOP), KeyboardButton(text=BTN_ADMIN)],
    ],
    resize_keyboard=True,
)


def sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=main_url())],
            [InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")],
        ]
    )


cancel_kb = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")]]
)


class Support(StatesGroup):
    waiting = State()


router = Router()
BOT_USERNAME = ""


def name_of(row) -> str:
    if row["username"]:
        return "@" + row["username"]
    return html.escape(row["full_name"] or str(row["user_id"]))


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    if not main_channel():
        return True
    try:
        m = await bot.get_chat_member(main_channel(), user_id)
        return m.status in ("member", "administrator", "creator", "restricted")
    except Exception as e:  # bot kanalda admin bo'lmasa shu yerga tushadi
        log.warning("get_chat_member xatosi: %s", e)
        return False


# ───────────────────────── Referalni hisoblash ─────────────────────────
async def get_ref_link(bot: Bot, user_id: int) -> str:
    """Har bir foydalanuvchiga "By Muhammad" kanaliga shaxsiy taklif havolasi."""
    row = db.execute("SELECT link FROM ref_links WHERE user_id=? AND channel=?",
                     (user_id, main_channel())).fetchone()
    if row:
        return row["link"]
    link = (await bot.create_chat_invite_link(main_channel(), name=f"ref_{user_id}")).invite_link
    db.execute("INSERT OR REPLACE INTO ref_links (user_id, channel, link) VALUES (?,?,?)",
               (user_id, main_channel(), link))
    db.commit()
    return link


def is_main_chat(chat) -> bool:
    mc = main_channel()
    return mc == str(chat.id) or (chat.username and mc.lower() == "@" + chat.username.lower())


@router.chat_member()
async def on_channel_join(event: ChatMemberUpdated, bot: Bot):
    """Kanalga kimdir shaxsiy havola orqali qo'shilsa — havola egasiga +1."""
    if not is_main_chat(event.chat) or not event.invite_link:
        return
    name = event.invite_link.name or ""
    if not name.startswith("ref_") or not name[4:].isdigit():
        return
    if event.old_chat_member.status not in ("left", "kicked"):
        return
    if event.new_chat_member.status not in ("member", "restricted"):
        return
    referrer, joiner = int(name[4:]), event.new_chat_member.user.id
    if referrer == joiner:
        return
    if not get_user(referrer):  # baza yangilangan bo'lsa ham hisob yo'qolmasin
        db.execute("INSERT OR IGNORE INTO users (user_id, joined_at) VALUES (?,?)",
                   (referrer, datetime.now(TZ).isoformat()))
    # bir odam faqat bir marta hisoblanadi (chiqib qayta kirsa ham)
    cur = db.execute("INSERT OR IGNORE INTO joins (joiner_id, referrer_id, joined_at) VALUES (?,?,?)",
                     (joiner, referrer, datetime.now(TZ).isoformat()))
    if cur.rowcount == 0:
        db.commit()
        return
    db.execute("UPDATE users SET ref_count=ref_count+1 WHERE user_id=?", (referrer,))
    db.commit()
    await notify_referrer(bot, referrer)


async def notify_referrer(bot: Bot, referrer_id: int):
    ref = get_user(referrer_id)
    if not ref:
        return
    count = ref["ref_count"]
    try:
        if count < target():
            await bot.send_message(
                ref["user_id"],
                f"🎉 Havolangiz orqali yangi odam qo'shildi!\n"
                f"Natija: <b>{count}/{target()}</b>. Yana {target() - count} ta qoldi.",
            )
        elif not ref["rewarded"]:
            await give_reward(bot, ref["user_id"])
        else:
            await bot.send_message(
                ref["user_id"], f"🎉 Yana bir odam qo'shildi! Jami: <b>{count}</b> ta."
            )
    except Exception as e:
        log.warning("Referrerga xabar yuborilmadi: %s", e)


async def give_reward(bot: Bot, user_id: int):
    if private_channel() is None:
        await bot.send_message(user_id, "🎉 Siz maqsadga yetdingiz! Havola tez orada yuboriladi.")
        await bot.send_message(ADMIN_ID, f"⚠️ {user_id} maqsadga yetdi, lekin yopiq kanal sozlanmagan. "
                                         "/yopiq_kanal bilan sozlang, keyin /havola " + str(user_id))
        return
    link = await bot.create_chat_invite_link(
        private_channel(), member_limit=1, name=f"ref_{user_id}"
    )
    db.execute(
        "UPDATE users SET rewarded=1, invite_link=? WHERE user_id=?",
        (link.invite_link, user_id),
    )
    db.commit()
    await bot.send_message(
        user_id,
        f"🔥 Tabriklaymiz! Siz {target()} ta odamni taklif qildingiz.\n\n"
        f"Yopiq darslar kanaliga havola (faqat siz uchun, 1 marta ishlaydi):\n"
        f"{link.invite_link}",
    )
    await bot.send_message(ADMIN_ID, f"🎁 {user_id} yopiq kanal havolasini oldi.")


# ───────────────────────── /start ─────────────────────────
@router.message(CommandStart())
async def start(message: Message, command: CommandObject, bot: Bot, state: FSMContext):
    await state.clear()
    user = message.from_user
    existing = get_user(user.id)

    if not existing:
        referred_by = None
        arg = command.args or ""
        if arg.startswith("ref_") and arg[4:].isdigit():
            rid = int(arg[4:])
            if rid != user.id and get_user(rid):
                referred_by = rid
        db.execute(
            "INSERT INTO users (user_id, full_name, username, referred_by, joined_at) "
            "VALUES (?,?,?,?,?)",
            (user.id, user.full_name, user.username, referred_by,
             datetime.now(TZ).isoformat()),
        )
    else:
        db.execute(
            "UPDATE users SET full_name=?, username=? WHERE user_id=?",
            (user.full_name, user.username, user.id),
        )
    db.commit()

    if not await is_subscribed(bot, user.id):
        await message.answer(
            f"Assalomu alaykum, {html.escape(user.first_name)}!\n\n"
            "Botdan foydalanish uchun avval kanalimizga obuna bo'ling 👇",
            reply_markup=sub_kb(),
        )
        return

    if user.id == ADMIN_ID:
        await message.answer("👑 Siz adminsiz. Sozlamalar: /sozlama, statistika: /stat")
    await message.answer(
        f"Assalomu alaykum, {html.escape(user.first_name)}! 👋\n\n"
        f"Do'stlaringizni taklif qiling — <b>{target()}</b> ta odam qo'shilsa, "
        "yopiq darslar kanaliga kirish havolasini olasiz 🎁",
        reply_markup=main_kb,
    )


@router.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, call.from_user.id):
        await call.answer("Siz hali obuna bo'lmagansiz ❗️", show_alert=True)
        return
    await call.message.delete()
    await call.message.answer(
        f"✅ Rahmat! Endi do'stlaringizni taklif qiling — <b>{target()}</b> ta odam "
        "qo'shilsa, yopiq darslar kanaliga havola olasiz 🎁",
        reply_markup=main_kb,
    )


# ───────────────────────── Menyu ─────────────────────────
@router.message(F.text == BTN_REF)
async def my_ref(message: Message, bot: Bot):
    try:
        link = await get_ref_link(bot, message.from_user.id)
    except Exception as e:
        log.error("Havola yaratilmadi: %s", e)
        await message.answer("Havola yaratishda xatolik. Iltimos, keyinroq urinib ko'ring.")
        await bot.send_message(ADMIN_ID, f"⚠️ Referal havola yaratilmadi: {e}")
        return
    await message.answer(
        "📢 <b>By Muhammad</b> kanaliga sizning shaxsiy havolangiz 👇\n\n"
        f"{link}\n\n"
        f"Shu havolani do'stlaringizga yuboring. Havolangiz orqali {target()} ta odam "
        "kanalga qo'shilsa — yopiq darslar kanaliga kirish havolasini olasiz 🎁"
    )


@router.message(F.text == BTN_STAT)
async def my_stat(message: Message, bot: Bot):
    u = get_user(message.from_user.id)
    if not u:
        await message.answer("Iltimos, /start bosing.")
        return
    count = u["ref_count"]
    if u["rewarded"]:
        text = (f"📊 Siz taklif qilganlar: <b>{count}</b> ta\n\n"
                f"✅ Yopiq kanal havolangiz:\n{u['invite_link']}")
    else:
        text = (f"📊 Siz taklif qilganlar: <b>{count}/{target()}</b>\n"
                f"Yana {max(target() - count, 0)} ta qoldi.")
    await message.answer(text)


def build_top_text() -> str:
    rows = db.execute(
        "SELECT * FROM users WHERE ref_count>0 ORDER BY ref_count DESC, joined_at ASC LIMIT ?",
        (TOP_COUNT,),
    ).fetchall()
    if not rows:
        return "🏆 Hozircha reyting bo'sh. Birinchi bo'ling!"
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>Eng ko'p odam taklif qilganlar</b> ({datetime.now(TZ):%d.%m.%Y})\n"]
    for i, r in enumerate(rows):
        mark = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{mark} {name_of(r)} — <b>{r['ref_count']}</b> ta")
    lines.append(f"\n👉 Siz ham qatnashing: @{BOT_USERNAME}")
    return "\n".join(lines)


@router.message(F.text == BTN_TOP)
async def top(message: Message):
    await message.answer(build_top_text())


# ───────────────────────── Adminga murojaat ─────────────────────────
@router.message(F.text == BTN_ADMIN)
async def ask_admin(message: Message, state: FSMContext):
    await state.set_state(Support.waiting)
    await message.answer(
        "Savolingiz yoki xabaringizni yozing (matn, rasm, ovozli xabar bo'lishi mumkin) 👇",
        reply_markup=cancel_kb,
    )


@router.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Bekor qilindi.")


@router.message(Support.waiting)
async def to_admin(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    u = message.from_user
    uname = f"@{u.username}" if u.username else "username yo'q"
    head = await bot.send_message(
        ADMIN_ID,
        f"📩 <b>Yangi murojaat</b>\n{html.escape(u.full_name)} ({uname}), ID: <code>{u.id}</code>\n"
        "Javob berish uchun pastdagi xabarga <b>Reply</b> qiling.",
    )
    copy = await message.copy_to(ADMIN_ID)
    db.executemany(
        "INSERT OR REPLACE INTO support (admin_msg_id, user_id) VALUES (?,?)",
        [(head.message_id, u.id), (copy.message_id, u.id)],
    )
    db.commit()
    await message.answer("✅ Xabaringiz yuborildi. Tez orada javob beramiz.", reply_markup=main_kb)


@router.message(F.chat.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(message: Message):
    row = db.execute(
        "SELECT user_id FROM support WHERE admin_msg_id=?",
        (message.reply_to_message.message_id,),
    ).fetchone()
    if not row:
        return
    try:
        await message.bot.send_message(row["user_id"], "📨 <b>Admindan javob:</b>")
        await message.copy_to(row["user_id"])
        await message.reply("✅ Yuborildi")
    except Exception as e:
        await message.reply(f"❌ Yuborilmadi: {e}")


# ───────────────────────── Admin buyruqlari ─────────────────────────
@router.message(Command("stat"), F.chat.id == ADMIN_ID)
async def admin_stat(message: Message):
    total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    counted = db.execute("SELECT COUNT(*) FROM joins").fetchone()[0]
    rewarded = db.execute("SELECT COUNT(*) FROM users WHERE rewarded=1").fetchone()[0]
    await message.answer(
        f"👥 Bot foydalanuvchilari: <b>{total}</b>\n"
        f"🔗 Havola orqali kanalga qo'shilganlar: <b>{counted}</b>\n"
        f"🎁 Yopiq kanalga havola olganlar: <b>{rewarded}</b>"
    )


@router.message(Command("post_top"), F.chat.id == ADMIN_ID)
async def admin_post_top(message: Message, bot: Bot):
    await bot.send_message(main_channel(), build_top_text())
    await message.answer("✅ Reyting kanalga joylandi.")


@router.message(Command("send"), F.chat.id == ADMIN_ID)
async def admin_send(message: Message, command: CommandObject, bot: Bot):
    """/send <user_id> <matn> — foydalanuvchiga to'g'ridan-to'g'ri yozish."""
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer("Foydalanish: /send 123456789 Salom!")
        return
    await bot.send_message(int(parts[0]), f"📨 <b>Admindan:</b>\n{html.escape(parts[1])}")
    await message.answer("✅ Yuborildi")


def settings_text() -> str:
    pc = private_channel()
    return (
        "⚙️ <b>Sozlamalar</b>\n\n"
        f"📢 Asosiy kanal: <code>{main_channel() or 'yo‘q'}</code>\n"
        f"🔒 Yopiq kanal: <code>{pc if pc else 'yo‘q'}</code>\n"
        f"🎯 Kerakli odam soni: <b>{target()}</b>\n"
        f"⏰ Reyting vaqti: <b>{top_time()}</b>\n\n"
        "O'zgartirish:\n"
        "/kanal @username — asosiy kanal\n"
        "/yopiq_kanal -100... — yopiq kanal (yoki yopiq kanaldan postni shu yerga forward qiling)\n"
        "/maqsad 5 — necha odam kerak\n"
        "/vaqt 20:00 — reyting vaqti\n"
        "/havola ID — foydalanuvchiga yopiq kanal havolasini qo'lda berish\n\n"
        "❗️ Bot ikkala kanalda ham admin bo'lishi shart."
    )


@router.message(Command("sozlama"), F.chat.id == ADMIN_ID)
async def admin_settings(message: Message):
    await message.answer(settings_text())


@router.message(Command("kanal"), F.chat.id == ADMIN_ID)
async def set_main(message: Message, command: CommandObject, bot: Bot):
    v = (command.args or "").strip()
    if not v.startswith("@") and not v.lstrip("-").isdigit():
        await message.answer(
            f"Hozirgi asosiy kanal: <code>{main_channel() or 'yo‘q'}</code>\n\n"
            "O'zgartirish uchun kanal username'ini yoki ID'sini yozing:\n"
            "<code>/kanal @kanal_username</code>\n"
            "Avval botni o'sha kanalga admin qilish shart."
        )
        return
    try:
        chat = await bot.get_chat(v)
        me = await bot.get_chat_member(chat.id, bot.id)
        if me.status != "administrator":
            raise ValueError("bot bu kanalda admin emas")
    except Exception as e:
        await message.answer(f"❌ Avval botni shu kanalga admin qiling. ({e})")
        return
    set_cfg("main_channel", "@" + chat.username if chat.username else str(chat.id))
    if chat.username:
        set_cfg("main_url", f"https://t.me/{chat.username}")
    else:  # yopiq/username'siz kanal — doimiy taklif havolasi
        link = chat.invite_link or (await bot.create_chat_invite_link(chat.id, name="bot")).invite_link
        set_cfg("main_url", link)
    await message.answer(f"✅ Asosiy kanal: {html.escape(chat.title)}\n\n" + settings_text())


async def save_private(message: Message, bot: Bot, chat_id: int):
    try:
        chat = await bot.get_chat(chat_id)
        test = await bot.create_chat_invite_link(chat_id, member_limit=1, name="test")
        await bot.revoke_chat_invite_link(chat_id, test.invite_link)
    except Exception as e:
        await message.answer(f"❌ Bot bu kanalda admin emas yoki taklif huquqi yo'q: {e}")
        return
    set_cfg("private_channel", str(chat.id))
    await message.answer(f"✅ Yopiq kanal: {html.escape(chat.title)}\n\n" + settings_text())


@router.message(Command("yopiq_kanal"), F.chat.id == ADMIN_ID)
async def set_private(message: Message, command: CommandObject, bot: Bot):
    v = (command.args or "").strip()
    if not v.lstrip("-").isdigit():
        await message.answer("Foydalanish: /yopiq_kanal -1001234567890\n"
                             "Yoki yopiq kanaldan istalgan postni shu yerga forward qiling.")
        return
    await save_private(message, bot, int(v))


@router.message(F.chat.id == ADMIN_ID, F.forward_origin.chat)
async def private_by_forward(message: Message, bot: Bot):
    await save_private(message, bot, message.forward_origin.chat.id)


@router.message(Command("maqsad"), F.chat.id == ADMIN_ID)
async def set_target(message: Message, command: CommandObject):
    v = (command.args or "").strip()
    if not v.isdigit() or int(v) < 1:
        await message.answer("Foydalanish: /maqsad 5")
        return
    set_cfg("target", v)
    await message.answer(settings_text())


@router.message(Command("vaqt"), F.chat.id == ADMIN_ID)
async def set_time(message: Message, command: CommandObject):
    v = (command.args or "").strip()
    try:
        v = datetime.strptime(v, "%H:%M").strftime("%H:%M")
    except ValueError:
        await message.answer("Foydalanish: /vaqt 20:00")
        return
    set_cfg("top_time", v)
    await message.answer(settings_text())


@router.message(Command("havola"), F.chat.id == ADMIN_ID)
async def manual_reward(message: Message, command: CommandObject, bot: Bot):
    v = (command.args or "").strip()
    if not v.isdigit():
        await message.answer("Foydalanish: /havola 123456789")
        return
    await give_reward(bot, int(v))
    await message.answer("✅ Bajarildi")


# ───────────────────────── Kunlik reyting ─────────────────────────
async def daily_top(bot: Bot):
    while True:
        now = datetime.now(TZ)
        today = now.strftime("%Y-%m-%d")
        # oxirgi e'lon sanasi bazada saqlanadi: bot qayta yonsa ham ikki marta chiqmaydi
        if now.strftime("%H:%M") >= top_time() and cfg("last_top") != today and main_channel():
            set_cfg("last_top", today)
            try:
                await bot.send_message(main_channel(), build_top_text())
                log.info("Kunlik reyting joylandi")
            except Exception as e:
                log.error("Reyting joylanmadi: %s", e)
        await asyncio.sleep(30)


async def main():
    global BOT_USERNAME
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    BOT_USERNAME = (await bot.get_me()).username
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(daily_top(bot))
    max_runtime = int(os.getenv("MAX_RUNTIME", "0"))  # GitHub Actions uchun: shuncha soniyadan keyin to'xtaydi
    if max_runtime:
        async def stop_later():
            await asyncio.sleep(max_runtime)
            log.info("MAX_RUNTIME tugadi, bot to'xtayapti")
            await dp.stop_polling()
        asyncio.create_task(stop_later())
    log.info("Bot ishga tushdi: @%s", BOT_USERNAME)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
