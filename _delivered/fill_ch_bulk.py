#!/usr/bin/env python3
"""
Массовое наполнение ru_ch / usa_ch кандидатами из офлайн-выгрузки БД (все
посты, а не только "трендовые" последних недель) — используются те же
серверные ручки /weights и /append, что и в fill_ch_dictionary.py, но список
кандидатов берётся не из /trend-candidates, а из локального CSV-файла
(lemma;frequency), который заранее посчитан по всему корпусу постов.

Скрипт САМ ведёт чекпоинт (файл рядом с candidates-file, суффикс .progress) —
поэтому его можно запускать в цикле (как fill_ch_dictionary.py раньше) с одним
и тем же --limit, и каждый следующий запуск продолжит с того места, где
остановился предыдущий, а не будет обрабатывать одно и то же.

Запуск (внутри контейнера сервера):

    docker compose cp ru_candidates.csv server:/app/scripts/ru_candidates.csv
    docker compose cp usa_candidates.csv server:/app/scripts/usa_candidates.csv
    docker compose cp fill_ch_bulk.py server:/app/scripts/fill_ch_bulk.py

    docker compose exec server python /app/scripts/fill_ch_bulk.py \
        --username admin --password admin --base ru \
        --candidates-file /app/scripts/ru_candidates.csv --limit 50

    (повторять с --base usa --candidates-file /app/scripts/usa_candidates.csv
     для usa_ch, когда решите её запускать)

Использует только stdlib (urllib) — ничего дополнительно ставить не нужно.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APPEND_BATCH_SIZE = 50


def _request(method: str, url: str, *, token: str | None = None, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} от {method} {url}: {body}") from exc


def login(base_url: str, username: str, password: str) -> str:
    resp = _request("POST", f"{base_url}/auth/login", payload={"username": username, "password": password})
    return resp["access_token"]


def get_weights(base_url: str, token: str, *, lemma: str, lang: str, provider: str | None, model: str | None) -> dict:
    params = {"lang": lang}
    if provider:
        params["provider"] = provider
    if model:
        params["model"] = model
    encoded_lemma = urllib.parse.quote(lemma, safe="")
    url = f"{base_url}/analyze/lemma/trend-candidates/{encoded_lemma}/weights?{urllib.parse.urlencode(params)}"
    return _request("GET", url, token=token)


def append_lemmas(base_url: str, token: str, *, lang: str, items: list[dict]) -> dict:
    params = {"lang": lang, "overwrite_existing": "false"}
    url = f"{base_url}/analyze/lemma/append?{urllib.parse.urlencode(params)}"
    return _request("POST", url, token=token, payload={"lemmas": items})


def chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def load_candidates(path: str) -> list[str]:
    lemmas = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader, None)  # header: lemma;frequency
        for row in reader:
            if row and row[0].strip():
                lemmas.append(row[0].strip())
    return lemmas


def load_state(state_path: str) -> int:
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            return json.load(f).get("next_index", 0)
    return 0


def save_state(state_path: str, next_index: int) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"next_index": next_index}, f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--base", required=True, choices=["ru", "usa"], help="ru -> ru_ch, usa -> usa_ch")
    parser.add_argument("--candidates-file", required=True, help="CSV lemma;frequency, отсортирован по убыванию частоты")
    parser.add_argument("--state-file", default=None, help="По умолчанию <candidates-file>.progress")
    parser.add_argument("--limit", type=int, default=50, help="Сколько лемм обработать за этот запуск (каждая = 1 вызов LLM)")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true", help="Сбросить чекпоинт и начать с начала списка")
    args = parser.parse_args()

    merged_lang = f"{args.base}_merged"
    write_lang = f"{args.base}_ch"
    state_path = args.state_file or f"{args.candidates_file}.progress"

    candidates = load_candidates(args.candidates_file)
    total = len(candidates)

    start = 0 if args.reset else load_state(state_path)
    if start >= total:
        print(f"Готово: все {total} кандидатов из {args.candidates_file} уже обработаны (чекпоинт={start}).")
        return

    to_process = candidates[start : start + args.limit]
    print(f"Всего кандидатов в файле: {total}. Чекпоинт: {start}. Берём {len(to_process)} (лимит --limit={args.limit}).")

    if args.dry_run:
        for lemma in to_process:
            print(f"  - {lemma}")
        print("--dry-run: LLM не вызывается, чекпоинт не двигается")
        return

    token = login(args.base_url, args.username, args.password)
    print("Авторизация прошла успешно")

    scored: list[dict] = []
    failed: list[str] = []
    for i, lemma in enumerate(to_process, start=1):
        try:
            item = get_weights(
                args.base_url, token,
                lemma=lemma, lang=merged_lang,
                provider=args.provider, model=args.model,
            )
            scored.append(item)
            print(f"[{i}/{len(to_process)}] {lemma} -> категория={item.get('category')!r}")
        except RuntimeError as exc:
            print(f"[{i}/{len(to_process)}] {lemma} -> ОШИБКА: {exc}", file=sys.stderr)
            failed.append(lemma)
            time.sleep(1)

    print(f"Успешно размечено LLM: {len(scored)} из {len(to_process)}")

    total_added = 0
    total_updated = 0
    for batch in chunks(scored, APPEND_BATCH_SIZE):
        resp = append_lemmas(args.base_url, token, lang=write_lang, items=batch)
        total_added += resp.get("added", 0) or 0
        total_updated += resp.get("updated", 0) or 0

    new_index = start + len(to_process)
    save_state(state_path, new_index)

    print("---")
    print(f"Записано в {write_lang}: добавлено={total_added} обновлено={total_updated}")
    print(f"Чекпоинт продвинут: {start} -> {new_index} из {total}")
    if failed:
        print(f"Не удалось получить веса для: {failed}", file=sys.stderr)


if __name__ == "__main__":
    main()
