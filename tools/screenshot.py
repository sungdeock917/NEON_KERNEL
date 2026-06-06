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
    ("8_orbit_aim_popup.png", "정비궤도 조준 팝업 (형태 모듈, T3 장착 시)", """() => {
        setChassisIndex(0);
        G.slots[0] = makeCore(3, ['mint','red']);  // Affix는 T3 코어 장착 중에만 등장/부착
        enterOrbit();
        G.candidates[0] = { core:null, boost:null, affix:{slot:'prefix',id:'giant',name:'거대한'}, ang:0, r:CFG.candidateR, taken:false, bob:0 };
        G.candidates[1] = { core:null, boost:null, affix:{slot:'suffix',id:'crit',name:'치명적인'}, ang:2.1, r:CFG.candidateR, taken:false, bob:0 };
        G.selCandIdx = 0;
        setAimToast(G.candidates[0]); G.aimToast.t = 0.3; // 조준 팝업: 형태 · 거대한
    }"""),
    ("9_orbit_aim_core.png", "정비궤도 조준 팝업 (코어 향함, 거동 글리프)", """() => {
        setChassisIndex(0);
        if (!G.slots[0]) G.slots[0] = makeT1Id('streamPing');
        enterOrbit();
        G.candidates[0] = { core: makeT1Id('heavyJunk'), boost:null, affix:null, ang:0, r:CFG.candidateR, taken:false, bob:0 };
        G.selCandIdx = 0;
        setAimToast(G.candidates[0]); G.aimToast.t = 0.3;
    }"""),
]

# 아웃게임(메타) 화면 — 게임 진입 없이 씬만 전환 (이름 M_ 접두로 구분)
META_SHOTS = [
    ("M1_main.png", "메인 화면", """() => {
        SAVE.currency = 740; SAVE.best.wave = 18; SAVE.best.t3 = 2; SAVE.slots = 4; SAVE.chassis = 'gwanglan';
        goScene('main');
    }"""),
    ("M2_select.png", "기체 선택 화면", """() => {
        SAVE.cleared = false; // 딥웹 잠금 표시
        goScene('select');
    }"""),
    ("M3_upgrade.png", "강화 화면 (3갈래)", """() => {
        SAVE.currency = 500; SAVE.slots = 3; SAVE.best.wave = 12;
        SAVE.phys = { rot: 1, hp: 2, intercept: 0, brake: 1 }; SAVE.startBoost = 1;
        goScene('upgrade');
    }"""),
    ("M4_result.png", "정산 화면", """() => {
        lastResult = { wave: 23, t3: 3, reward: 246, firstClear: 40, cleared: false, record: true };
        SAVE.currency = 986;
        goScene('result');
    }"""),
]


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=2)
        pg.goto(INDEX.as_uri())
        pg.wait_for_function("typeof SAVE !== 'undefined' && typeof startGame === 'function'", timeout=8000)
        # 인게임 화면: 매 샷마다 새 게임 진입 후 셋업
        for fname, desc, setup in SHOTS:
            pg.evaluate("() => startGame()")
            time.sleep(0.4)
            pg.evaluate(setup)
            time.sleep(0.6)
            pg.locator("canvas").screenshot(path=str(OUT / fname))
            print(f"saved {fname}  — {desc}")
        # 메타 화면
        for fname, desc, setup in META_SHOTS:
            pg.evaluate(setup)
            time.sleep(0.5)
            pg.locator("canvas").screenshot(path=str(OUT / fname))
            print(f"saved {fname}  — {desc}")
        b.close()
    print(f"\n{len(SHOTS) + len(META_SHOTS)} shots -> {OUT}")


if __name__ == "__main__":
    main()
