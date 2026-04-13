import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN_HERE")
DB_PATH = "tasks.db"

# Conversation states
WAITING_TASK_TEXT, WAITING_MEMBER, WAITING_TAG, WAITING_PRIORITY = range(4)

MEMBERS = {
    "0": "Андрій",
    "1": "Оксана",
    "2": "Василь",
    "3": "Людмила",
}

TAGS = {
    "dev": "💻 Розробка",
    "design": "🎨 Дизайн",
    "marketing": "📣 Маркетинг",
    "qa": "🔍 QA",
    "admin": "📋 Адмін",
}

PRIORITIES = {
    "🔴": "Критично",
    "🟡": "Середній",
    "⚪": "Низький",
}

STATUSES = {
    "todo": "📌 До виконання",
    "inprogress": "🔄 В процесі",
    "review": "👀 Перевірка",
    "done": "✅ Виконано",
}


# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            member TEXT DEFAULT '0',
            tag TEXT DEFAULT 'admin',
            priority TEXT DEFAULT '⚪',
            status TEXT DEFAULT 'todo',
            done INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def db():
    return sqlite3.connect(DB_PATH)


def get_tasks(chat_id, member=None, status=None):
    conn = db()
    c = conn.cursor()
    q = "SELECT * FROM tasks WHERE chat_id=?"
    params = [chat_id]
    if member is not None:
        q += " AND member=?"
        params.append(member)
    if status is not None:
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY id DESC"
    rows = c.execute(q, params).fetchall()
    conn.close()
    return rows


def add_task(chat_id, text, member, tag, priority, status="todo"):
    conn = db()
    conn.execute(
        "INSERT INTO tasks (chat_id, text, member, tag, priority, status) VALUES (?,?,?,?,?,?)",
        (chat_id, text, member, tag, priority, status)
    )
    conn.commit()
    conn.close()


def complete_task(task_id):
    conn = db()
    conn.execute("UPDATE tasks SET done=1, status='done' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()


def delete_task(task_id):
    conn = db()
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()


def update_status(task_id, status):
    done = 1 if status == "done" else 0
    conn = db()
    conn.execute("UPDATE tasks SET status=?, done=? WHERE id=?", (status, done, task_id))
    conn.commit()
    conn.close()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def task_line(row):
    _, chat_id, text, member, tag, priority, status, done, _ = row
    check = "✅" if done else "⬜"
    member_name = MEMBERS.get(member, member)
    tag_label = TAGS.get(tag, tag)
    return f"{check} {priority} {text}\n   👤 {member_name} · {tag_label}"


def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Всі завдання", callback_data="list_all"),
            InlineKeyboardButton("➕ Нове завдання", callback_data="new_task"),
        ],
        [
            InlineKeyboardButton("👥 По учаснику", callback_data="by_member"),
            InlineKeyboardButton("📊 Статус", callback_data="by_status"),
        ],
        [
            InlineKeyboardButton("📈 Статистика", callback_data="stats"),
        ]
    ])


# ─── Handlers ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привіт! Це командний таск-менеджер.\n\nОберіть дію:",
        reply_markup=main_keyboard()
    )


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Головне меню:", reply_markup=main_keyboard())


async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "list_all":
        await show_all_tasks(query, chat_id)

    elif data == "new_task":
        await query.message.reply_text("✏️ Введіть назву нового завдання:")
        return WAITING_TASK_TEXT

    elif data == "by_member":
        kb = [[InlineKeyboardButton(f"👤 {name}", callback_data=f"member_{mid}")] for mid, name in MEMBERS.items()]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
        await query.edit_message_text("Оберіть учасника:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("member_"):
        mid = data.split("_")[1]
        tasks = get_tasks(chat_id, member=mid)
        name = MEMBERS.get(mid, mid)
        if not tasks:
            text = f"👤 {name}\n\nЗавдань немає."
        else:
            lines = [f"👤 *{name}* — {len(tasks)} завдань\n"]
            for row in tasks:
                lines.append(task_line(row))
            text = "\n".join(lines)
        kb = [[InlineKeyboardButton("◀️ Назад", callback_data="by_member")]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "by_status":
        kb = [[InlineKeyboardButton(label, callback_data=f"status_{key}")] for key, label in STATUSES.items()]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
        await query.edit_message_text("Оберіть статус:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("status_"):
        st = data.split("_")[1]
        tasks = get_tasks(chat_id, status=st)
        label = STATUSES.get(st, st)
        if not tasks:
            text = f"{label}\n\nЗавдань немає."
        else:
            lines = [f"*{label}* — {len(tasks)} завдань\n"]
            for row in tasks:
                lines.append(task_line(row))
            text = "\n".join(lines)
        kb = []
        if tasks:
            for row in tasks:
                tid = row[0]
                kb.append([InlineKeyboardButton(f"✅ Виконати: {row[2][:30]}", callback_data=f"done_{tid}")])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="by_status")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("done_"):
        tid = int(data.split("_")[1])
        complete_task(tid)
        await query.answer("✅ Виконано!", show_alert=True)
        await show_all_tasks(query, chat_id)

    elif data.startswith("delete_"):
        tid = int(data.split("_")[1])
        delete_task(tid)
        await query.answer("🗑 Видалено", show_alert=True)
        await show_all_tasks(query, chat_id)

    elif data == "stats":
        await show_stats(query, chat_id)

    elif data == "back_main":
        await query.edit_message_text("Головне меню:", reply_markup=main_keyboard())


async def show_all_tasks(query, chat_id):
    tasks = get_tasks(chat_id)
    if not tasks:
        text = "📋 Список завдань порожній.\nДодайте перше завдання!"
    else:
        active = [t for t in tasks if not t[7]]
        done = [t for t in tasks if t[7]]
        lines = [f"📋 *Всі завдання* ({len(tasks)})\n"]
        if active:
            lines.append("*Активні:*")
            for row in active[:10]:
                lines.append(task_line(row))
        if done:
            lines.append(f"\n*Виконані ({len(done)}):*")
            for row in done[:5]:
                lines.append(task_line(row))
        text = "\n".join(lines)

    kb = [
        [InlineKeyboardButton("➕ Додати", callback_data="new_task")],
        [InlineKeyboardButton("⚙️ Керувати", callback_data="manage")],
        [InlineKeyboardButton("◀️ Меню", callback_data="back_main")],
    ]
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def show_stats(query, chat_id):
    all_tasks = get_tasks(chat_id)
    total = len(all_tasks)
    done = sum(1 for t in all_tasks if t[7])
    inprog = sum(1 for t in all_tasks if t[6] == "inprogress")
    critical = sum(1 for t in all_tasks if t[5] == "🔴" and not t[7])

    lines = [
        "📈 *Статистика команди*\n",
        f"📌 Всього завдань: *{total}*",
        f"✅ Виконано: *{done}*",
        f"🔄 В процесі: *{inprog}*",
        f"🔴 Критичних: *{critical}*",
        "",
    ]
    for mid, name in MEMBERS.items():
        mt = [t for t in all_tasks if t[3] == mid]
        md = sum(1 for t in mt if t[7])
        pct = round(md / len(mt) * 100) if mt else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"👤 *{name}*: {len(mt)} завд. [{bar}] {pct}%")

    kb = [[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


# ─── Conversation: add task ───────────────────────────────────────────────────

async def receive_task_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_task_text"] = update.message.text
    kb = [[InlineKeyboardButton(name, callback_data=f"pick_member_{mid}")] for mid, name in MEMBERS.items()]
    await update.message.reply_text("👤 Кому призначити?", reply_markup=InlineKeyboardMarkup(kb))
    return WAITING_MEMBER


async def pick_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mid = query.data.split("_")[2]
    ctx.user_data["new_task_member"] = mid
    kb = [[InlineKeyboardButton(label, callback_data=f"pick_tag_{key}")] for key, label in TAGS.items()]
    await query.edit_message_text("🏷 Оберіть категорію:", reply_markup=InlineKeyboardMarkup(kb))
    return WAITING_TAG


async def pick_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tag = query.data.split("_")[2]
    ctx.user_data["new_task_tag"] = tag
    kb = [[InlineKeyboardButton(f"{pri} {label}", callback_data=f"pick_pri_{pri}")] for pri, label in PRIORITIES.items()]
    await query.edit_message_text("🎯 Пріоритет:", reply_markup=InlineKeyboardMarkup(kb))
    return WAITING_PRIORITY


async def pick_priority(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pri = query.data.replace("pick_pri_", "")
    ud = ctx.user_data
    add_task(
        chat_id=query.message.chat_id,
        text=ud["new_task_text"],
        member=ud["new_task_member"],
        tag=ud["new_task_tag"],
        priority=pri,
    )
    member_name = MEMBERS.get(ud["new_task_member"], "")
    tag_label = TAGS.get(ud["new_task_tag"], "")
    await query.edit_message_text(
        f"✅ Завдання додано!\n\n"
        f"📝 {ud['new_task_text']}\n"
        f"👤 {member_name} · {tag_label} · {pri}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 До списку", callback_data="list_all")]])
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Скасовано.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u, c: receive_task_text(u, c) or WAITING_TASK_TEXT, pattern="^new_task$")],
        states={
            WAITING_TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_text)],
            WAITING_MEMBER: [CallbackQueryHandler(pick_member, pattern="^pick_member_")],
            WAITING_TAG: [CallbackQueryHandler(pick_tag, pattern="^pick_tag_")],
            WAITING_PRIORITY: [CallbackQueryHandler(pick_priority, pattern="^pick_pri_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
