import OpenAI from 'openai';

export type Analysis = {
  sentiment: -1 | 0 | 1;
  topics: string[];
  summary: string;
};

const fallback = (text: string): Analysis => {
  // basic heuristic fallback when no API key is set
  const t = text.toLowerCase();
  const negative = ['crisis','escándalo','acus','corrup','violenc','renuncia','cae','pierde'];
  const positive = ['logro','avanza','crece','aprob','gana','lidera','mejora','récord'];
  let score = 0;
  for (const w of positive) if (t.includes(w)) score++;
  for (const w of negative) if (t.includes(w)) score--;
  const sent = score > 0 ? 1 : score < 0 ? -1 : 0;
  return { sentiment: sent, topics: [], summary: text.slice(0, 280) };
};

export async function analyzeText(text: string, apiKey?: string): Promise<Analysis> {
  if (!apiKey) return fallback(text);
  const client = new OpenAI({ apiKey });
  const resp = await client.chat.completions.create({
    model: 'gpt-4o-mini',
    messages: [{
      role: 'system',
      content: 'Eres un analista político. Devuelve JSON con keys: sentiment (-1,0,1), topics (array de palabras clave cortas), summary (máx 2 frases).'
    },{
      role: 'user',
      content: text.slice(0, 4000)
    }],
    temperature: 0.2,
    response_format: { type: 'json_object' },
  });
  const content = resp.choices[0].message.content ?? "{}";
  try {
    const data = JSON.parse(content);
    return {
      sentiment: Math.max(-1, Math.min(1, Number(data.sentiment) || 0)) as -1|0|1,
      topics: Array.isArray(data.topics) ? data.topics.slice(0, 10) : [],
      summary: typeof data.summary === 'string' ? data.summary : '',
    };
  } catch {
    return fallback(text);
  }
}
