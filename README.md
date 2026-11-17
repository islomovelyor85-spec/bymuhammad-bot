# By Muhammad — rasmiy bot

## Nima qiladi
- **✉️ Adminga yozish** — foydalanuvchi xabari sizga keladi. Unga **Reply** qilsangiz, javob foydalanuvchiga boradi.
- **🔗 Referal havolam** — har kimga shaxsiy havola: `t.me/BOT?start=ref_ID`.
- Havola orqali kelgan odam **kanalga obuna bo'lgandagina** hisoblanadi (soxta hisobni oldini oladi). Bir odam faqat bir marta hisoblanadi.
- **5 ta** odam qo'shilsa — yopiq kanalga **bir martalik** (faqat 1 kishi kira oladigan) havola avtomatik yuboriladi.
- Har kuni soat **20:00** (Toshkent) asosiy kanalga TOP-10 reyting chiqadi.

## Admin buyruqlari (faqat sizda ishlaydi)
- `/stat` — statistika
- `/post_top` — reytingni hozir kanalga joylash
- `/send 123456789 matn` — foydalanuvchiga yozish

## O'rnatish
1. @BotFather → `/newbot` → token oling.
2. Botni **asosiy kanalga** va **yopiq kanalga** admin qiling (yopiq kanalda "Foydalanuvchilarni taklif qilish" huquqi yoqilgan bo'lsin).
3. Yopiq kanal ID sini bilish: kanaldan biror postni @userinfobot ga forward qiling (`-100...` bilan boshlanadi).
4. `.env.example` faylini `.env` deb nusxalang va qiymatlarni to'ldiring.
5. Ishga tushirish:
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python bot.py
   ```

Bot 24/7 ishlashi uchun uni serverga (VPS, Railway, Render va h.k.) qo'yish kerak — kompyuter o'chsa bot ham to'xtaydi.
