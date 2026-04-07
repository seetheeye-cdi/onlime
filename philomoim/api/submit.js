export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { name, contact, work, book, note } = req.body;

  if (!name || !contact) {
    return res.status(400).json({ error: 'name, contact required' });
  }

  const lines = [
    `[철학모임 신청]`,
    ``,
    `이름: ${name}`,
    `전화번호: ${contact}`,
  ];
  if (work) lines.push(`하시는 일: ${work}`);
  if (book) lines.push(`읽고 싶은 책/철학자: ${book}`);
  if (note) lines.push(`한마디: ${note}`);

  const text = lines.join('\n');

  const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
  const CHAT_ID = process.env.TELEGRAM_CHAT_ID;

  try {
    const tgRes = await fetch(
      `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chat_id: CHAT_ID,
          text,
        }),
      }
    );

    if (!tgRes.ok) {
      console.error('Telegram error:', await tgRes.text());
      return res.status(500).json({ error: 'Failed to send notification' });
    }

    return res.status(200).json({ ok: true });
  } catch (err) {
    console.error('Error:', err);
    return res.status(500).json({ error: 'Internal error' });
  }
}
