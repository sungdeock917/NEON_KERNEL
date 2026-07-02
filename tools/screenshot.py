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
    # 텔레그래프 샷: dur를 크게 잡아 0.6s sleep 동안 RAF가 예고를 resolve하지 못하게 고정(prog 0.7 유지)
    ("B1_walle.png", "보스 WALL_E (방패 + 집속 일제사 예고)", """() => {
        startWave(10); G.boss.hp = G.boss.hpMax * 0.7;
        startBossTelegraph(G.boss); G.boss.tele.dur = 1000; G.boss.tele.t = 700; // 집속 예고선(prog 0.7 고정)
    }"""),
    ("B2_antiv.png", "보스 ANTI_V (에러블록 + 멀티 락온 예고)", """() => {
        startWave(20); G.boss.hp = G.boss.hpMax * 0.6;
        G.boss.blocks.push({ang: 1.0, life: 4, max: 4});
        G.boss.blocks.push({ang: 3.4, life: 4, max: 4});
        doSpawn(0.6, ENEMY.shooter); doSpawn(2.5, ENEMY.shooter);
        startBossTelegraph(G.boss); G.boss.tele.dur = 1000; G.boss.tele.t = 700; // 3방향 락온선(prog 0.7 고정)
    }"""),
    ("B3_panic.png", "보스 KERNEL_PANIC (테두리=HP + 수축 링 예고)", """() => {
        startWave(30); G.boss.hp = G.boss.hpMax * 0.55;
        for (let i = 0; i < 8; i++) doSpawn(i / 8 * Math.PI * 2, i % 2 ? ENEMY.runner : ENEMY.bouncer);
        startBossTelegraph(G.boss); G.boss.tele.dur = 1000; G.boss.tele.t = 700; // 전방위 링 예고(prog 0.7 고정)
    }"""),
    ("B4_revive.png", "이어하기 오퍼 (보스전 사망, 시안 카운트다운 링)", """() => {
        startWave(20); G.boss.hp = G.boss.hpMax * 0.5;
        G.hp = 0; die(); // 보스전 사망 → 이어하기 오퍼
        G.reviveOffer.t = G.reviveOffer.dur * 0.35;
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


# 모바일 뷰포트(390×844) — 텔레그래프/보스가 좁은 세로 화면에서도 읽히는지 (이름 Bm_ 접두)
MOBILE_SHOTS = [
    ("Bm1_walle_mobile.png", "모바일: WALL_E 집속 예고(보스 측에서)", """() => {
        startWave(10); G.boss.hp = G.boss.hpMax * 0.7;
        startBossTelegraph(G.boss); G.boss.tele.dur = 1000; G.boss.tele.t = 700;
    }"""),
    ("Bm3_panic_mobile.png", "모바일: PANIC 수축 링 예고(화면 비례)", """() => {
        startWave(30); G.boss.hp = G.boss.hpMax * 0.55;
        startBossTelegraph(G.boss); G.boss.tele.dur = 1000; G.boss.tele.t = 700;
    }"""),
    ("Bm2_combat_mobile.png", "모바일: 8방위 스폰 예고+적 — 타원 스폰 전방향 가시(화면비 정규화)", """() => {
        G.enemies.length = 0; G.warnings.length = 0; G.waveActive = false; G.spawnTimer = 1e9;
        for (let k = 0; k < 8; k++) { const a = k / 8 * Math.PI * 2;
          const def = [ENEMY.runner, ENEMY.bouncer, ENEMY.shooter, ENEMY.shielder][k % 4];
          G.warnings.push({ ang: a, t: 0.7, def }); doSpawn(a, def); }
    }"""),
    ("Bm4_orbit_mobile.png", "모바일: 정비궤도 후보 — 타원 클램프(좌우 클립 없음)", """() => {
        G.slots[0] = makeT1Id('streamPing'); enterOrbit();
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
        # 모바일 뷰포트
        pgm = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        pgm.goto(INDEX.as_uri())
        pgm.wait_for_function("typeof SAVE !== 'undefined' && typeof startGame === 'function'", timeout=8000)
        for fname, desc, setup in MOBILE_SHOTS:
            pgm.evaluate("() => startGame()")
            time.sleep(0.4)
            pgm.evaluate(setup)
            time.sleep(0.6)
            pgm.locator("canvas").screenshot(path=str(OUT / fname))
            print(f"saved {fname}  — {desc}")
        b.close()
    print(f"\n{len(SHOTS) + len(META_SHOTS) + len(MOBILE_SHOTS)} shots -> {OUT}")


if __name__ == "__main__":
    main()
