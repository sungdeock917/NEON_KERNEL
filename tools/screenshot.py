#!/usr/bin/env python3
"""NEON KERNEL 상태별 스크린샷 캡처 (Playwright / Python)

prototype/index.html 을 띄워 기체/상태별 화면을 PNG로 저장한다.
VS Code 채팅에서 결과를 바로 볼 수 있게 tools/shots/ 아래에 떨군다.

  python tools/screenshot.py
"""
import sys, io, pathlib, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "prototype" / "index.html"
OUT = ROOT / "tools" / "shots"
OUT.mkdir(exist_ok=True)

# (파일명, 설명, 셋업 JS) — 셋업 후 잠깐 굴려서 RAF가 그 상태를 렌더하게 함
SHOTS = [
    ("1_legacy.png", "레거시-99 기본 전투", """() => { setChassisIndex(0); }"""),
    ("2_proxy_shield.png", "프록시 보호막 링", """() => {
        setChassisIndex(1); G.shield = G.shieldMax * 0.66;
    }"""),
    ("3_glitch.png", "글리치-Zero 과열 정지 플리커", """() => {
        setChassisIndex(3); G.glitchCooldown = 0.5;
    }"""),
    ("4_gwanglan.png", "광랜-X 투사체×3 탄막", """() => {
        setChassisIndex(2); reapplyChassisToAllCores();
    }"""),
    ("5_deepweb_markers.png", "딥웹 저주(붉은X)+대박(금빛) 마커", """() => {
        setChassisIndex(4);
        // 슬롯을 채워 마커가 보이게: 0=저주, 2=대박
        if (!G.slots[0]) G.slots[0] = makeT1Id('streamPing');
        if (!G.slots[2]) G.slots[2] = makeT1Id('dotSnippet');
        applyChassisToCore(G.slots[0]); applyChassisToCore(G.slots[2]);
        G.slots[0].deepweb = 'curse'; G.slots[0].cursed = true;
        G.slots[2].deepweb = 'jackpot';
    }"""),
    ("6_affix_mutated.png", "Affix 변이 코어 (금빛 헤일로+접두/접미 핍)", """() => {
        setChassisIndex(0);
        if (!G.slots[0]) G.slots[0] = makeT1Id('streamPing');
        if (!G.slots[2]) G.slots[2] = makeT1Id('heavyJunk');
        setAffixes(G.slots[0], { prefix: 'giant', suffix: 'crit' });
        setAffixes(G.slots[2], { prefix: 'orbital', suffix: 'drain' });
    }"""),
    ("7_affix_ddos_curse.png", "마이너스 Affix 디도스 (붉은 핍 + 시야 가림)", """() => {
        setChassisIndex(0);
        if (!G.slots[0]) G.slots[0] = makeT1Id('streamPing');
        setAffixes(G.slots[0], { suffix: 'ddos' });
    }"""),
]


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=2)
        pg.goto(INDEX.as_uri())
        pg.wait_for_function("typeof G !== 'undefined' && G && G.t >= 0", timeout=8000)
        time.sleep(1.2)  # 코어 장착·웨이브 시작 대기
        for fname, desc, setup in SHOTS:
            pg.evaluate(setup)
            time.sleep(0.7)  # 셋업 상태를 몇 프레임 렌더
            path = OUT / fname
            pg.locator("canvas").screenshot(path=str(path))
            print(f"saved {path.name}  — {desc}")
        b.close()
    print(f"\n{len(SHOTS)} shots -> {OUT}")


if __name__ == "__main__":
    main()
