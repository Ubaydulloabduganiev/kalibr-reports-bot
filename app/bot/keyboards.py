from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.bot.texts import t


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="O‘zbekcha", callback_data="lang:uz")],
            [InlineKeyboardButton(text="Русский", callback_data="lang:ru")],
        ]
    )


def menu_keyboard(language: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(language, "daily")), KeyboardButton(text=t(language, "weekly"))],
            [KeyboardButton(text=t(language, "history"))],
        ],
        resize_keyboard=True,
    )


def collection_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(language, "finish"), callback_data="report:finish")]]
    )


def confirmation_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(language, "confirm"), callback_data="report:confirm")],
            [InlineKeyboardButton(text=t(language, "correct"), callback_data="report:correct")],
            [InlineKeyboardButton(text=t(language, "cancel"), callback_data="report:cancel")],
        ]
    )


def manager_keyboard(report_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"mgr:approve:{report_id}"),
                InlineKeyboardButton(text="↩️ Return", callback_data=f"mgr:return:{report_id}"),
            ],
            [
                InlineKeyboardButton(text="💬 Comment", callback_data=f"mgr:comment:{report_id}"),
                InlineKeyboardButton(text="👤 Reassign", callback_data=f"mgr:reassign:{report_id}"),
            ],
            [
                InlineKeyboardButton(text="📌 Create task", callback_data=f"mgr:task:{report_id}"),
                InlineKeyboardButton(text="🚨 Escalate", callback_data=f"mgr:escalate:{report_id}"),
            ],
            [
                InlineKeyboardButton(text="✔️ Resolved", callback_data=f"mgr:resolve:{report_id}"),
                InlineKeyboardButton(text="📊 History", callback_data=f"mgr:history:{report_id}"),
            ],
            [InlineKeyboardButton(text="📈 Department summary", callback_data=f"mgr:summary:{report_id}")],
        ]
    )


def deal_match_keyboard(matches, language: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{match.name} — {match.price:,.0f} UZS" if match.price is not None else match.name,
            callback_data=f"deal:link:{match.id}",
        )]
        for match in matches[:5]
    ]
    rows.append([InlineKeyboardButton(
        text="Mos bitim yo‘q" if language == "uz" else "Нет подходящей сделки",
        callback_data="deal:none",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
