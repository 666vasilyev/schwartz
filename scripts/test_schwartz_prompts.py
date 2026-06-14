"""
Тест вариантов промптов для извлечения ценностей Шварца из текста (gemma4:31b / Ollama).

Запуск:
    pip install httpx --break-system-packages
    python scripts/test_schwartz_prompts.py

Результаты: scripts/schwartz_prompt_results.json
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

# ── Конфигурация ──────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://10.0.21.10:11434"
MODEL = "gemma4:31b"
TIMEOUT = 120.0

SCHWARTZ_KEYS = (
    "self_direction", "stimulation", "hedonism", "achievement", "power",
    "security", "conformity", "tradition", "benevolence", "universalism",
)

# ── Тестовые тексты ───────────────────────────────────────────────────────────
TEST_TEXTS = {
    "roller_coaster": (
        "В ТЕХАСЕ ВОСЕМЬ ЧЕЛОВЕК ПРОВИСЕЛИ ВНИЗ ГОЛОВОЙ НА АМЕРИКАНСКИХ ГОРКАХ ЧЕТЫРЕ ЧАСА. "
        "Аттракцион «Superman: Tower of Power» в парке Six Flags остановился из-за технической неполадки. "
        "Пассажиров эвакуировали с помощью специальных лестниц. Никто серьёзно не пострадал."
    ),
    "tuna_fish": (
        "БРАТЬЯ В АВСТРАЛИИ ВЫЛОВИЛИ ТУНЦА НА 73 ТЫСЯЧИ ДОЛЛАРОВ, НО НЕ СМОГЛИ ЕГО ПРОДАТЬ. "
        "Рыбаки из Аделаиды поймали синеперого тунца весом 176 кг, однако местные рыбные рынки "
        "отказались его принять из-за отсутствия надлежащих документов. Рыба пошла на личное потребление."
    ),
    "protest": (
        "Тысячи людей вышли на улицы Москвы в защиту свободы слова и против цензуры в интернете. "
        "Участники акции несли плакаты с надписями «Свобода информации» и «Нет блокировкам». "
        "Организаторы призвали власти отменить законы об ограничении доступа к зарубежным сайтам."
    ),
    "military_victory": (
        "Российская армия освободила стратегически важный населённый пункт на востоке страны. "
        "Министерство обороны сообщило об уничтожении техники и живой силы противника. "
        "Командование подчеркнуло героизм бойцов и призвало граждан поддержать армию."
    ),
}

# ── Варианты промптов ─────────────────────────────────────────────────────────

TEMPLATE_JSON = '{"self_direction":?,"stimulation":?,"hedonism":?,"achievement":?,"power":?,"security":?,"conformity":?,"tradition":?,"benevolence":?,"universalism":?}'

PROMPTS: dict[str, dict] = {

    # 1. Текущий (длинный русский system + короткий user)
    "current": {
        "system": (
            "Ты оцениваешь, насколько в данном фрагменте текста читаема или активируема каждая из "
            "10 базовых ценностей Шварца, по шкале от 0.0 (почти нет) до 1.0 (очень сильно выражено). "
            "Смысл измерителей:\n"
            "- self_direction — свобода мыслей, выбора, независимость, творчество\n"
            "- stimulation — смена впечатлений, риск, крутые ощущения, новизна\n"
            "- hedonism — удовольствие, кайф, комфорт «здесь и сейчас»\n"
            "- achievement — соревнование, успех, демонстрация своих сил, цели, KPI\n"
            "- power — власть, доминирование, статус, деньги как контроль, давление\n"
            "- security — национальная/личная/семейная безопасность, стабильность\n"
            "- conformity — норма, правила, «так не принято», сдержанность\n"
            "- tradition — вера, обычай, «так положено», духовные традиции\n"
            "- benevolence — теплота, помощь своим (семья, близкий круг)\n"
            "- universalism — справедливость, равноправие, экология, мировой мир\n\n"
            "Верни ТОЛЬКО JSON-объект с этими 10 ключами, значения float 0.0..1.0. "
            "Никакого markdown, никакого текста вне JSON."
        ),
        "user_tmpl": "Проанализируй фрагмент и верни JSON по инструкции.\n\n---\n{text}",
        "response_format": True,
    },

    # 2. Шаблон-заполнялка (модели проще заполнить готовую форму)
    "template_fill": {
        "system": (
            "You are a text analyst. Score how strongly each of Schwartz's 10 basic values "
            "is expressed in the given text. Scale: 0.0 (absent) to 1.0 (dominant).\n\n"
            "Value definitions:\n"
            "- self_direction: freedom of thought, autonomy, creativity, independence\n"
            "- stimulation: excitement, novelty, risk, adventure, variety\n"
            "- hedonism: pleasure, enjoyment, fun, sensory gratification\n"
            "- achievement: success, ambition, competence, goals, winning\n"
            "- power: authority, dominance, status, wealth, control over others\n"
            "- security: safety, stability, order, protection, threat avoidance\n"
            "- conformity: following rules, obedience, self-restraint, social norms\n"
            "- tradition: respect for custom, religion, heritage, humility\n"
            "- benevolence: caring for close ones, loyalty, honesty within in-group\n"
            "- universalism: justice, equality, tolerance, environment, world peace\n\n"
            "IMPORTANT: Return ONLY the completed JSON below, replacing each ? with a float 0.0-1.0. "
            "No markdown, no explanation.\n\n"
            f"JSON template to fill: {TEMPLATE_JSON}"
        ),
        "user_tmpl": "Text to analyze:\n\n{text}",
        "response_format": False,
    },

    # 3. Двухшаговый: сначала объяснить, потом JSON
    "think_then_json": {
        "system": (
            "You are an expert in Schwartz's Theory of Basic Human Values. "
            "Analyze the provided text for the presence of 10 Schwartz values.\n\n"
            "Step 1: Briefly identify which themes/values are present in the text (1-2 sentences).\n"
            "Step 2: Score each value 0.0-1.0 based on how strongly it appears.\n\n"
            "Value keys and their meaning:\n"
            "self_direction=autonomy/creativity, stimulation=novelty/excitement, "
            "hedonism=pleasure/fun, achievement=success/goals, power=control/status, "
            "security=safety/order, conformity=rules/norms, tradition=customs/heritage, "
            "benevolence=care for close ones, universalism=justice/environment\n\n"
            "End your response with EXACTLY this JSON block (replace ? with floats):\n"
            "```json\n"
            f"{TEMPLATE_JSON}\n"
            "```"
        ),
        "user_tmpl": "Analyze this text:\n\n{text}",
        "response_format": False,
    },

    # 4. Few-shot: один пример + задание
    "few_shot": {
        "system": (
            "Rate how strongly each Schwartz value appears in a text (0.0=absent, 1.0=dominant). "
            "Return ONLY a JSON object with these 10 keys.\n\n"
            "Example:\n"
            'Input: "Activists marched to demand equal rights and environmental protection."\n'
            'Output: {"self_direction":0.6,"stimulation":0.3,"hedonism":0.0,"achievement":0.3,'
            '"power":0.2,"security":0.1,"conformity":0.1,"tradition":0.0,'
            '"benevolence":0.4,"universalism":0.9}\n\n'
            "Schwartz key meanings:\n"
            "self_direction=independence/creativity | stimulation=novelty/risk | "
            "hedonism=pleasure | achievement=success/goals | power=dominance/status | "
            "security=safety/stability | conformity=rules/norms | tradition=customs/religion | "
            "benevolence=care for in-group | universalism=justice/equality/ecology\n\n"
            "Now rate the new text. Return ONLY the JSON object, nothing else."
        ),
        "user_tmpl": "{text}",
        "response_format": False,
    },

    # 5. Минималистичный с явным форматом вывода
    "minimal_explicit": {
        "system": (
            "Task: score Schwartz values in the text below. Output only valid JSON.\n\n"
            "Rules:\n"
            "1. Each of the 10 keys must be present\n"
            "2. Values are floats between 0.0 and 1.0\n"
            "3. Most values for a neutral news text will be low (0.0-0.3)\n"
            "4. Only raise a value if the text clearly mentions or evokes that theme\n"
            "5. No markdown, no text outside the JSON object\n\n"
            "Keys: self_direction, stimulation, hedonism, achievement, power, "
            "security, conformity, tradition, benevolence, universalism\n\n"
            "Definitions:\n"
            "self_direction: personal freedom, autonomy, choosing own path\n"
            "stimulation: thrill, novelty, excitement, bold experiences\n"
            "hedonism: physical pleasure, enjoyment, comfort\n"
            "achievement: personal success, ambition, competing, winning\n"
            "power: control over others, authority, wealth, dominance\n"
            "security: threat/danger, protection, safety, law and order\n"
            "conformity: obedience to rules, social pressure, self-discipline\n"
            "tradition: religion, cultural heritage, respect for elders/customs\n"
            "benevolence: helping family/friends, loyalty, caring for close ones\n"
            "universalism: global justice, human rights, nature/ecology, world peace"
        ),
        "user_tmpl": "Text: {text}\n\nJSON:",
        "response_format": False,
    },

    # 6. Русский системный с явным примером (русский текст + пример)
    "russian_few_shot": {
        "system": (
            "Оцени выраженность 10 ценностей Шварца в тексте. Шкала: 0.0 (не выражено) – 1.0 (очень сильно).\n\n"
            "Ключи и их смысл:\n"
            "self_direction = независимость, свобода выбора, творчество\n"
            "stimulation = новизна, риск, острые ощущения, приключения\n"
            "hedonism = удовольствие, радость, комфорт, наслаждение\n"
            "achievement = успех, амбиции, победа, достижение целей\n"
            "power = власть, контроль, статус, богатство, господство\n"
            "security = безопасность, стабильность, защита, порядок\n"
            "conformity = следование правилам, послушание, сдержанность\n"
            "tradition = обычаи, религия, наследие, почитание старших\n"
            "benevolence = забота о близких, семья, лояльность, дружба\n"
            "universalism = справедливость, экология, права человека, мир\n\n"
            "Пример:\n"
            'Текст: "Волонтёры высадили тысячу деревьев в городском парке, чтобы улучшить экологию."\n'
            'Ответ: {"self_direction":0.3,"stimulation":0.1,"hedonism":0.0,"achievement":0.4,'
            '"power":0.0,"security":0.2,"conformity":0.1,"tradition":0.0,'
            '"benevolence":0.5,"universalism":0.8}\n\n'
            "Верни ТОЛЬКО JSON-объект с 10 ключами, без markdown и пояснений."
        ),
        "user_tmpl": "Текст: {text}\n\nJSON:",
        "response_format": False,
    },
}


# ── Вспомогательные функции ───────────────────────────────────────────────────

def extract_json_from_text(text: str) -> dict | None:
    """Извлечь JSON из ответа (в т.ч. из markdown-блоков)."""
    # Попытка 1: парсим как есть
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Попытка 2: ищем ```json ... ``` блок
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Попытка 3: ищем первый {...} в тексте
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


def normalize(raw: dict | None) -> dict[str, float]:
    if not raw:
        return {k: 0.0 for k in SCHWARTZ_KEYS}
    out = {}
    for k in SCHWARTZ_KEYS:
        v = raw.get(k, 0.0)
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        out[k] = round(max(0.0, min(1.0, f)), 3)
    return out


def bar(val: float, width: int = 20) -> str:
    filled = round(val * width)
    return "█" * filled + "░" * (width - filled)


async def call_ollama(
    client: httpx.AsyncClient,
    system: str,
    user: str,
    use_response_format: bool,
    think: bool = False,
) -> tuple[str, float]:
    """Вызвать Ollama, вернуть (raw_text, elapsed_sec).

    gemma4:31b — thinking model: content пустой, текст в message.thinking.
    think=False отключает thinking mode (рекомендуется для JSON-задач).
    """
    payload: dict = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
        "stream": False,
        "think": think,  # False = отключить thinking mode
    }
    if use_response_format:
        payload["response_format"] = {"type": "json_object"}

    t0 = time.monotonic()
    resp = await client.post(
        f"{OLLAMA_BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=TIMEOUT,
    )
    elapsed = time.monotonic() - t0
    resp.raise_for_status()
    data = resp.json()
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    thinking = msg.get("thinking") or ""
    # Если content пустой, но есть thinking — значит модель не вернула ответ в content
    if not content and thinking:
        # Пробуем извлечь JSON из thinking (fallback)
        content = f"[FROM THINKING]: {thinking[:300]}"
    return content, elapsed, thinking


async def run_prompt(
    client: httpx.AsyncClient,
    prompt_name: str,
    prompt_cfg: dict,
    text_name: str,
    text: str,
    think: bool = False,
) -> dict:
    user_msg = prompt_cfg["user_tmpl"].format(text=text)
    try:
        raw, elapsed, thinking = await call_ollama(
            client,
            prompt_cfg["system"],
            user_msg,
            prompt_cfg["response_format"],
            think=think,
        )
        parsed = extract_json_from_text(raw)
        values = normalize(parsed)
        ok = parsed is not None and len(parsed) > 0
        return {
            "prompt": prompt_name,
            "text": text_name,
            "think": think,
            "elapsed_s": round(elapsed, 1),
            "ok": ok,
            "raw_len": len(raw),
            "raw_preview": raw[:300].replace("\n", " "),
            "thinking_len": len(thinking),
            "values": values,
        }
    except Exception as e:
        return {
            "prompt": prompt_name,
            "text": text_name,
            "think": think,
            "elapsed_s": -1,
            "ok": False,
            "raw_len": 0,
            "raw_preview": f"ERROR: {e}",
            "thinking_len": 0,
            "values": {k: 0.0 for k in SCHWARTZ_KEYS},
        }


def print_result(r: dict) -> None:
    status = "✅" if r["ok"] else "❌"
    think_flag = f" think={'on' if r.get('think') else 'off'}"
    print(f"\n{'─'*70}")
    print(f"{status} [{r['prompt']}] on [{r['text']}]{think_flag}  ({r['elapsed_s']}s)")
    print(f"   content ({r['raw_len']} chars): {r['raw_preview']}")
    print(f"   thinking ({r.get('thinking_len', 0)} chars)")
    if r["ok"]:
        vals = r["values"]
        for k in SCHWARTZ_KEYS:
            v = vals[k]
            if v > 0:
                print(f"   {k:<18} {v:.3f}  {bar(v, 15)}")
        nonzero = sum(1 for v in vals.values() if v > 0)
        print(f"   → {nonzero}/10 non-zero values")
    else:
        print("   → parse failed or empty dict")


async def main() -> None:
    results = []
    texts_to_test = list(TEST_TEXTS.items())
    prompts_to_test = list(PROMPTS.items())

    total = len(texts_to_test) * len(prompts_to_test)
    print(f"Тест промптов Шварца: {len(prompts_to_test)} промптов × {len(texts_to_test)} текста = {total} запросов")
    print(f"Модель: {MODEL}  |  Ollama: {OLLAMA_BASE_URL}\n")

    # Проверка доступности Ollama
    async with httpx.AsyncClient() as probe:
        try:
            r = await probe.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
            models = [m["name"] for m in r.json().get("models", [])]
            print(f"Ollama OK. Модели: {models[:5]}")
        except Exception as e:
            print(f"❌ Ollama недоступна: {e}")
            sys.exit(1)

    async with httpx.AsyncClient() as client:
        # Сначала быстрая диагностика: один промпт, один текст, оба режима think
        print("\n" + "="*70)
        print("ДИАГНОСТИКА: think=True vs think=False (few_shot / roller_coaster)")
        for think_mode in [True, False]:
            r = await run_prompt(
                client, "few_shot", PROMPTS["few_shot"],
                "roller_coaster", TEST_TEXTS["roller_coaster"],
                think=think_mode,
            )
            results.append(r)
            print_result(r)

        # Основной прогон: все промпты, think=False
        for prompt_name, prompt_cfg in prompts_to_test:
            print(f"\n{'='*70}")
            print(f"ПРОМПТ: {prompt_name}  (response_format={prompt_cfg['response_format']}, think=False)")
            for text_name, text in texts_to_test:
                r = await run_prompt(client, prompt_name, prompt_cfg, text_name, text, think=False)
                results.append(r)
                print_result(r)

    # ── Сводная таблица ───────────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("СВОДКА: успешных парсингов и среднее число ненулевых значений")
    print(f"{'Промпт':<22} {'OK':<8} {'Nonzero avg':<14} {'Avg time'}")
    print("─" * 60)
    for prompt_name in PROMPTS:
        group = [r for r in results if r["prompt"] == prompt_name]
        ok_count = sum(1 for r in group if r["ok"])
        nonzero_avg = sum(
            sum(1 for v in r["values"].values() if v > 0) for r in group
        ) / max(len(group), 1)
        avg_time = sum(r["elapsed_s"] for r in group if r["elapsed_s"] > 0) / max(
            sum(1 for r in group if r["elapsed_s"] > 0), 1
        )
        bar_ok = "✅" * ok_count + "❌" * (len(group) - ok_count)
        print(f"{prompt_name:<22} {bar_ok:<8} {nonzero_avg:.1f}/10         {avg_time:.1f}s")

    # ── Сохранить JSON ────────────────────────────────────────────────────────
    out_path = Path(__file__).parent / "schwartz_prompt_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nРезультаты сохранены: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
