from __future__ import annotations

import asyncio
from datetime import time

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.core.models import Department, ReportSchedule, ReportTemplate, ReportType, Role, ScheduleKind

DEPARTMENTS = [
    ("retail", "Chakana savdo do‘konlari", "Розничные магазины", "stores"),
    ("call_center", "Call-markaz", "Колл-центр", "call_center"),
    ("b2b_sales", "B2B savdo", "B2B-продажи", "office"),
    ("marketing", "Marketing", "Маркетинг", "office"),
    ("publishing", "Nashriyot", "Издательство", "office"),
    ("rights", "Huquqlar boshqaruvi", "Управление правами", "office"),
    ("translation", "Tarjima", "Перевод", "office"),
    ("editing", "Tahrir", "Редактура", "office"),
    ("warehouse", "Ombor", "Склад", "office"),
    ("finance", "Moliya", "Финансы", "office"),
    ("hr", "HR", "HR", "office"),
    ("management", "Rahbariyat", "Руководство", "managers"),
    ("marketplace", "Marketplace", "Маркетплейсы", "office"),
]

UNIVERSAL_UZ = [
    "Bugun nima bajarildi?",
    "Qanday o‘lchanadigan natija olindi?",
    "Nima tugallanmay qoldi?",
    "Qanday muammo yoki blokatorlar paydo bo‘ldi?",
    "Yordam yoki tasdiq kerakmi?",
    "Ertaga nima rejalashtirilgan?",
    "Shoshilinch masala bormi?",
]
UNIVERSAL_RU = [
    "Что выполнено сегодня?",
    "Какой измеримый результат получен?",
    "Что осталось незавершённым?",
    "Какие проблемы или блокеры появились?",
    "Нужна ли помощь или согласование?",
    "Что запланировано на завтра?",
    "Есть ли срочный вопрос?",
]


WEEKLY_UZ = [
    "Bu haftadagi asosiy yutuqlar nimalar?",
    "KPI natijasi maqsadga nisbatan qanday?",
    "Qaysi muhim ishlar tugallanmay qoldi?",
    "Qaysi blokatorlar hafta davomida takrorlandi?",
    "Keyingi haftaga qanday risklar bor?",
    "Qanday yordam yoki tasdiqlar kerak?",
    "Keyingi haftaning ustuvorliklari nimalar?",
]
WEEKLY_RU = [
    "Каковы главные достижения недели?",
    "Каков результат KPI по сравнению с целью?",
    "Какие важные задачи остались незавершёнными?",
    "Какие блокеры повторялись в течение недели?",
    "Какие риски есть на следующую неделю?",
    "Какая помощь или согласования необходимы?",
    "Каковы приоритеты на следующую неделю?",
]

ROLE_QUESTIONS = {
    "retail": ["Savdo tushumi, xaridlar soni, sotilgan kitoblar, o‘rtacha chek, qaytarishlar va kam qolgan tovarlarni kiriting."],
    "call_center": ["Qo‘ng‘iroqlar, erishilgan suhbatlar, yangi leadlar, buyurtmalar, follow-up va asosiy e’tirozlarni kiriting."],
    "b2b_sales": ["Bog‘langan tashkilotlar, uchrashuvlar, takliflar, bitim qiymati, qarorlar va keyingi qadamlarni kiriting."],
    "marketing": ["Kontent, kampaniyalar, reach, leadlar, reklama xarajati va keyingi testlarni kiriting."],
    "publishing": ["Loyihalar, qo‘lyozma, verstka, bosma, deadline va tasdiq talablarini kiriting."],
    "rights": ["Huquq egalari, offerlar, javoblar, shartnoma, avans/royalti va huquqiy risklarni kiriting."],
    "translation": ["So‘z/sahifa hajmi, loyiha foizi, terminologiya muammosi va tugash prognozini kiriting."],
    "editing": ["Tahrir qilingan hajm, sifat muammolari, muallif/tarjimon savollari va deadline holatini kiriting."],
    "warehouse": ["Qabul, jo‘natma, qoldiq farqi, shikast, kechikish va zudlik bilan to‘ldiriladigan pozitsiyalarni kiriting."],
    "finance": ["Kirim-chiqim, debitor/kreditor, kassa farqi, to‘lovlar va moliyaviy risklarni kiriting."],
    "hr": ["Yollash, davomat, intizom, onboarding, xodim muammolari va maxfiylik holatini kiriting."],
    "management": ["Bo‘lim natijalari, qarorlar, eskalatsiya, kompaniya risklari va ertangi ustuvorliklarni kiriting."],
    "marketplace": ["Buyurtmalar, tushum, konversiya, qoldiq, qaytarish, reklama va kartochka muammolarini kiriting."],
}


async def seed() -> None:
    await init_db()
    async with SessionLocal() as session:
        for code, name_uz, name_ru, group_code in DEPARTMENTS:
            department = await session.scalar(select(Department).where(Department.code == code))
            if not department:
                department = Department(code=code, name_uz=name_uz, name_ru=name_ru, group_code=group_code)
                session.add(department)
                await session.flush()
            for report_type, suffix, questions_uz, questions_ru in [
                (ReportType.DAILY, "daily", UNIVERSAL_UZ, UNIVERSAL_RU),
                (ReportType.WEEKLY, "weekly", WEEKLY_UZ, WEEKLY_RU),
            ]:
                exists = await session.scalar(
                    select(ReportTemplate).where(
                        ReportTemplate.department_id == department.id,
                        ReportTemplate.report_type == report_type,
                    )
                )
                if not exists:
                    session.add(
                        ReportTemplate(
                            name=f"{code}-{suffix}",
                            report_type=report_type,
                            department_id=department.id,
                            questions_uz=questions_uz + ROLE_QUESTIONS.get(code, []),
                            questions_ru=questions_ru,
                        )
                    )
        if not await session.scalar(select(Role).where(Role.code == "employee")):
            session.add(Role(code="employee", name_uz="Xodim", name_ru="Сотрудник"))
        if not await session.scalar(select(Role).where(Role.code == "manager")):
            session.add(Role(code="manager", name_uz="Rahbar", name_ru="Руководитель", is_manager=True, permissions=["approve", "return", "comment", "reassign", "task", "escalate", "resolve"]))

        schedules = [
            ("Call centre daily", ScheduleKind.DAILY_PROMPT, "call_center", time(18, 30), None, 60),
            ("Stores daily", ScheduleKind.DAILY_PROMPT, "stores", time(21, 0), None, 60),
            ("Office daily", ScheduleKind.DAILY_PROMPT, "office", time(21, 0), None, 60),
            ("Managers daily", ScheduleKind.DAILY_PROMPT, "managers", time(21, 30), None, 60),
            ("CEO daily summary", ScheduleKind.DAILY_SUMMARY, "all", time(22, 0), None, 0),
            ("Call centre weekly", ScheduleKind.WEEKLY_PROMPT, "call_center", time(18, 30), 5, 90),
            ("Stores weekly", ScheduleKind.WEEKLY_PROMPT, "stores", time(21, 0), 5, 90),
            ("Office weekly", ScheduleKind.WEEKLY_PROMPT, "office", time(21, 0), 5, 90),
            ("Managers weekly", ScheduleKind.WEEKLY_PROMPT, "managers", time(21, 30), 5, 90),
            ("CEO weekly summary", ScheduleKind.WEEKLY_SUMMARY, "all", time(23, 0), 5, 0),
            ("CEO monthly summary", ScheduleKind.MONTHLY_SUMMARY, "all", time(23, 0), None, 0),
        ]
        for name, kind, group, local_time, weekday, grace in schedules:
            if not await session.scalar(select(ReportSchedule).where(ReportSchedule.name == name)):
                session.add(
                    ReportSchedule(
                        name=name,
                        kind=kind,
                        group_code=group,
                        local_time=local_time,
                        weekday=weekday,
                        grace_minutes=grace,
                    )
                )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
