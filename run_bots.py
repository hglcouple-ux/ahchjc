"""
Запускает app.py (экономический бот) и mafia_bot.py (бот мафии) как два
подпроцесса ВНУТРИ ОДНОГО Railway-сервиса.

Это важно: оба бота читают/пишут один и тот же файл bot_data.db. Если
задеплоить их как ДВА РАЗНЫХ сервиса на Railway — это будут два разных
контейнера с разными файловыми системами, и bot_data.db у них будет разный.
Поэтому Railway должен запускать именно этот файл как единственную команду
старта (Start Command), а он уже сам поднимет оба бота рядом.

Если один из ботов падает — раннер завершает работу целиком (весь сервис),
чтобы Railway перезапустил контейнер и подняло оба бота заново, а не оставлял
"наполовину живой" сервис с одним упавшим ботом.
"""

import asyncio
import signal
import sys


async def run_process(name: str, cmd: list[str]) -> int:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    print(f"[run_bots] Запущен {name}, pid={process.pid}")
    return_code = await process.wait()
    print(f"[run_bots] {name} завершился с кодом {return_code}")
    return return_code


async def main() -> None:
    tasks = [
        asyncio.create_task(run_process("app.py (экономика)", [sys.executable, "app.py"])),
        asyncio.create_task(run_process("mafia_bot.py (мафия)", [sys.executable, "mafia_bot.py"])),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    # Если один из ботов упал/вышел — гасим второй и завершаем процесс,
    # чтобы Railway перезапустил весь сервис целиком.
    for task in pending:
        task.cancel()
    for task in pending:
        try:
            await task
        except asyncio.CancelledError:
            pass

    exit_code = 0
    for task in done:
        exit_code = task.result() or exit_code

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
