#!/usr/bin/env python3
"""NEON KERNEL 자동 검증 하네스 (Playwright / Python)

이 환경엔 node가 없어 JS용 Playwright 대신 Python Playwright를 쓴다.
실제 브라우저로 prototype/index.html 을 띄워:
  1) 콘솔 에러 / 페이지 예외(throw) 를 수집
  2) 게임 RAF(loop: update→render)가 살아있는지(G.t 증가) 확인
     → CLAUDE.md 교훈: 렌더 크래시는 RAF를 멈춘다. G.t 정지로 잡는다.
  3) 신규/주요 코드 경로를 강제 구동(기체 5종, 압축 훅, 딥웹 룰렛,
     저주 슬롯잠금, 신규 렌더 분기)해서 그 와중에 에러가 안 나는지 확인

사용:
  python tools/verify_game.py                # 기본(headless)
  python tools/verify_game.py --headed       # 화면 띄워서
  python tools/verify_game.py --seconds 4    # 라이브 구동 시간

종료코드: 0=PASS, 1=FAIL(에러 또는 RAF 정지)
"""
import sys, time, pathlib, argparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "prototype" / "index.html"

# 페이지 안에서 실행할 드라이브 스크립트.
# 모든 신규 코드 경로를 합성으로 강제 실행하고, 던지면 {ok:false, where, msg} 반환.
DRIVE_JS = r"""
() => {
  const log = [];
  const step = (where, fn) => { try { fn(); log.push("OK   "+where); }
    catch(e){ log.push("FAIL "+where+": "+(e&&e.stack||e)); throw Object.assign(new Error(where+": "+e), {where}); } };
  try {
    step("boot", () => { newGame(); }); // 아웃게임 도입으로 로드 시 G 미생성 → 먼저 부팅
    step("globals-present", () => {
      for (const n of ["G","CHASSIS","setChassisIndex","rollDeepweb","canCompress","SAVE","goScene",
                       "applyChassisToCore","reapplyChassisToAllCores","makeT1Id","newGame","metaRunMods"]) {
        if (typeof eval(n) === "undefined") throw new Error("missing global: "+n);
      }
    });

    // 기체 5종 전부: 전환 + 코어 재적용 + 각 기체 압축 훅 + 신규 렌더 상태 주입
    for (let i = 0; i < CHASSIS.length; i++) {
      const ch = CHASSIS[i];
      step("setChassis:"+ch.id, () => setChassisIndex(i));

      // 압축 성공 훅(광랜 복리 reapply / 딥웹 룰렛)이 던지지 않는지
      step("onCompress:"+ch.id, () => {
        const core = makeT1Id("streamPing");
        applyChassisToCore(core);
        if (G.chassis && G.chassis.onCompressionSuccess) G.chassis.onCompressionSuccess(G, core, {});
      });

      // 신규 렌더 분기를 강제로 켠다 (실제 RAF가 다음 프레임에 그린다)
      step("inject-render-state:"+ch.id, () => {
        G.shield = (G.shieldMax || 12) * 0.5;     // 프록시 보호막 링
        G.glitchCooldown = 0.3;                    // 글리치 과열 플리커
        if (G.slots[0]) { G.slots[0].deepweb = "curse"; G.slots[0].cursed = true; } // 딥웹 저주 마커
        if (G.slots[2]) { G.slots[2].deepweb = "jackpot"; }                          // 딥웹 대박 마커
      });
    }

    // 딥웹 룰렛: 3분기(대박/중간/저주)가 모두 던지지 않는지 — 확률 강제 주입
    step("rollDeepweb-branches", () => {
      const real = Math.random;
      for (const r of [0.05, 0.45, 0.95]) {          // jackpot / normal / curse
        Math.random = () => r;
        const c = makeT1Id("dotSnippet"); applyChassisToCore(c); rollDeepweb(c);
        if (!c.deepweb) throw new Error("rollDeepweb set no flag at r="+r);
      }
      Math.random = real;
    });

    // 저주 슬롯 잠금: cursed 코어는 canCompress가 null
    step("cursed-lock", () => {
      const a = makeT1Id("streamPing"), b = makeT1Id("streamPing");
      a.cursed = true;
      if (canCompress(a, b) !== null) throw new Error("cursed core still compressable");
      const c = makeT1Id("streamPing"), d = makeT1Id("streamPing");
      if (canCompress(c, d) === null) throw new Error("same-color T1 should compress");
    });

    // Affix 스탯 레이어: 거대한=bulletR↑dmg↑, 과부하=dmg↑. fx 플래그 세팅.
    step("affix-stat-layer", () => {
      const c = makeT1Id("streamPing");
      const b0 = { dmg: c.dmg, br: c.bulletR };
      setAffixes(c, { prefix: "giant", suffix: "overload" });
      if (!(c.dmg > b0.dmg) || !(c.bulletR > b0.br)) throw new Error("giant/overload should raise dmg/bulletR");
      setAffixes(c, null);
      if (Math.abs(c.dmg - b0.dmg) > 1e-6) throw new Error("affix clear should restore base dmg");
    });

    // Affix fx 플래그: crit/vulnOnHit/affixFrag/lifesteal/ddos가 affixFx에 실림
    step("affix-fx-flags", () => {
      const checks = [["crit","crit"],["format","vulnOnHit"],["split","affixFrag"],["drain","lifesteal"],["ddos","ddos"]];
      for (const [aff, key] of checks) {
        const c = makeT1Id("streamPing");
        const isPrefix = (aff==="split");
        setAffixes(c, isPrefix ? { prefix: aff } : { suffix: aff });
        if (!c.affixFx || c.affixFx[key] == null) throw new Error(aff+" → affixFx."+key+" 누락");
      }
    });

    // Affix bparam 일관성: beam 코어 + 거대한(dmg×1.3) → beamDmgps도 스케일 (base.dmg=0 probe 경로)
    step("affix-beam-scale", () => {
      const spec = T2_CORES.find(s => s.behavior === "beam");
      if (!spec) return;
      const c = makeT2FromIds(spec.parents[0], spec.parents[1]);
      const base = c.bparams.beamDmgps;
      setAffixes(c, { prefix: "giant" }); // dmg×1.3
      if (!(c.bparams.beamDmgps > base * 1.2)) throw new Error("거대한이 beamDmgps도 스케일해야(현=" + c.bparams.beamDmgps + ")");
    });

    // random/curse 헬퍼
    step("affix-random-curse", () => {
      const a = makeT1Id("dotSnippet"); setAffixes(a, "random");
      if (!hasAffix(a)) throw new Error("random affix 미적용");
      const b = makeT1Id("dotSnippet"); setAffixes(b, "curse");
      if (!isNegAffix(b.affixes)) throw new Error("curse는 neg여야");
    });

    // 유형C 모듈: addAffix는 단일 슬롯만 설정(나머지 보존), rollAffixModule은 양수만
    step("affix-module", () => {
      const c = makeT1Id("streamPing");
      addAffix(c, "prefix", "giant"); addAffix(c, "suffix", "crit");
      if (c.affixes.prefix !== "giant" || c.affixes.suffix !== "crit") throw new Error("addAffix 슬롯 보존 실패");
      for (let i = 0; i < 20; i++) { const m = rollAffixModule();
        if (!AFFIX_BY_ID[m.id] || AFFIX_BY_ID[m.id].kind === "neg") throw new Error("모듈 보상에 마이너스/무효"); }
    });

    // 유형C 보상 흐름: 후보→대상선택(boost단계, T3 한정)→부착 (orbitConfirm 경로)
    step("affix-reward-flow", () => {
      G.slots[0] = makeCore(3, ["mint", "red"]); // Affix 부착 대상은 T3 한정
      enterOrbit();
      G.candidates[0] = { core: null, boost: null, affix: rollAffixModule(), ang: 0, r: CFG.candidateR, taken: false, bob: 0 };
      G.selCandIdx = 0;
      orbitConfirm();
      if (G.orbitStep !== "boost") throw new Error("affix 후보 확정→대상선택 단계 실패");
      if (!affixableSlots().length) throw new Error("T3 대상 목록이 비어있음");
      orbitConfirm();
      if (!G.slots.some(c => c && c.tier === 3 && hasAffix(c))) throw new Error("T3 코어 affix 부착 실패");
    });

    // T3 한정 검증: T1만 있으면 affixableSlots 비고, 등장조건 hasT3 거짓
    step("affix-t3-only", () => {
      newGame(); G.slots = [makeT1Id("streamPing"), null, null, null, null, null];
      if (affixableSlots().length !== 0) throw new Error("T1만 있는데 affix 대상이 잡힘");
      G.slots[2] = makeCore(3, ["mint", "purple"]);
      if (affixableSlots().length !== 1) throw new Error("T3 장착 후 affix 대상 1개여야");
    });

    // SF 토스트(일시, 합성결과용)
    step("toast", () => {
      G.toasts = []; pushToast("스트리밍(T2)", "straight", "#7fe9ff");
      if (!G.toasts.length) throw new Error("pushToast 실패");
    });

    // 조준 팝업: 정비궤도 진입 시 설정 → 탁으로 갱신 → 보상 확정 시 해제
    step("aim-popup", () => {
      if (!G.slots.some(c => c)) G.slots[0] = makeT1Id("streamPing");
      enterOrbit();
      if (!G.aimToast || !G.aimToast.name) throw new Error("진입 시 조준 팝업 미설정");
      orbitTap();
      if (!G.aimToast) throw new Error("탁 후 조준 팝업 사라짐");
      orbitConfirm();
      if (G.aimToast) throw new Error("보상 확정 후에도 조준 팝업 잔류");
    });

    // ===== 빔(레이저) 버그 수정 회귀 =====
    step("beam-intercepts-ebullet", () => {
      newGame();
      const spec = T2_CORES.find(s => s.behavior === "beam");
      G.slots[0] = makeT2FromIds(spec.parents[0], spec.parents[1]);
      G.bullets = []; G.ebullets = [];
      fireSlot(0);
      const beam = G.bullets.find(b => b.behavior === "beam");
      if (!beam) throw new Error("빔 미생성");
      const ex = beam.x + Math.cos(beam.angle) * 100, ey = beam.y + Math.sin(beam.angle) * 100;
      G.ebullets.push({ x: ex, y: ey, vx: 0, vy: 0, life: 1, r: 4 });
      collide(0.016);
      if (G.ebullets[0].life > 0) throw new Error("빔이 적탄을 요격 못함");
    });
    step("beam-no-stack", () => {
      newGame();
      const spec = T2_CORES.find(s => s.behavior === "beam");
      const c = makeT2FromIds(spec.parents[0], spec.parents[1]);
      G.slots[0] = c; G.bullets = [];
      fireSlot(0);
      const beam = G.bullets.find(b => b.behavior === "beam");
      // life가 발사주기(interval×1.1)에 맞아야 — 과거 고정 0.06이면 중첩 누적
      if (beam.life > c.interval * 1.2 + 1e-6) throw new Error("빔 life가 발사주기보다 김(중첩): " + beam.life);
    });

    // ===== 아웃게임(메타) =====
    step("meta-save", () => {
      if (!SAVE || SAVE.v !== 1) throw new Error("SAVE 손상");
      const mods = metaRunMods();
      if (mods.slots !== SAVE.slots || mods.hpMax !== 100 + SAVE.phys.hp * 20) throw new Error("metaRunMods 불일치");
    });
    step("meta-scenes", () => {
      for (const s of ["main", "select", "upgrade", "result", "game"]) { goScene(s); if (scene !== s) throw new Error("goScene 실패:" + s); }
    });
    step("meta-buy", () => {
      SAVE.currency = 9999; const hp0 = SAVE.phys.hp;
      buyPhys(PHYS_LIST.find(p => p.key === "hp"));
      if (SAVE.phys.hp !== hp0 + 1) throw new Error("buyPhys 미작동");
      const sb0 = SAVE.startBoost; buyStartBoost(); if (SAVE.startBoost !== sb0 + 1) throw new Error("buyStartBoost 미작동");
      // 슬롯: 진척조건 미충족 시 구매 불가
      SAVE.slots = 3; SAVE.best.wave = 0; const sl0 = SAVE.slots; buySlot();
      if (SAVE.slots !== sl0) throw new Error("진척조건 없이 슬롯 개방됨");
      SAVE.best.wave = 30; buySlot(); if (SAVE.slots !== 4) throw new Error("조건 충족 후 슬롯 개방 실패");
    });
    step("meta-reward", () => {
      newGame(); G.wave = 12; G.slots[0] = makeCore(3, ["mint", "red"]);
      const cur0 = SAVE.currency; G.ended = false; endGame(false);
      if (scene !== "result" || !lastResult || lastResult.wave !== 12) throw new Error("endGame 정산 실패");
      if (SAVE.currency <= cur0) throw new Error("재화 미적립");
    });
    step("meta-deepweb-lock", () => {
      SAVE.cleared = false;
      if (!chassisLocked(CHASSIS.find(c => c.id === "deepweb"))) throw new Error("미클리어 시 딥웹 잠금이어야");
      SAVE.cleared = true;
      if (chassisLocked(CHASSIS.find(c => c.id === "deepweb"))) throw new Error("클리어 후 딥웹 해제여야");
    });

    // 정상 상태로 리셋 + 게임 씬 진입(라이브 구동에서 update/G.t 돌도록)
    step("reset", () => { SAVE.chassis = "legacy"; startGame(); });
  } catch (e) {
    return { ok: false, where: e.where || "?", msg: String(e), log };
  }
  return { ok: true, log };
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="브라우저 창 표시")
    ap.add_argument("--seconds", type=float, default=3.0, help="라이브 구동 시간(초)")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    url = INDEX.as_uri()
    console_errors, page_errors = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page()
        page.on("console", lambda m: console_errors.append(f"[{m.type}] {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        page.goto(url)
        # 게임 부팅 대기: G 정의 + 루프 1회 이상
        page.wait_for_function("typeof SAVE !== 'undefined' && typeof newGame === 'function'", timeout=8000)

        # 신규 코드 경로 강제 구동
        result = page.evaluate(DRIVE_JS)

        # RAF 생존 확인: G.t 가 시간이 지나며 증가해야 한다(렌더 크래시면 멈춤)
        t0 = page.evaluate("G.t")
        time.sleep(args.seconds)
        # 라이브 구동 중 실제 입력도 몇 번 흘려 update/render 경로 자극
        page.keyboard.press("Space")     # 탁(회전 반전)
        page.keyboard.down("Space"); time.sleep(0.4); page.keyboard.up("Space")  # 꾹(브레이크)
        # A키로 Affix 순환(없음→무작위→저주) — 변이 글리프 마커·DDoS 오버레이 렌더 자극
        for _ in range(3):
            page.keyboard.press("KeyA"); time.sleep(0.35)
        page.keyboard.press("Enter")     # 정비 궤도 진입
        time.sleep(0.6)
        t1 = page.evaluate("G.t")

        browser.close()

    # 결과 판정
    print("=" * 56)
    print("NEON KERNEL 검증 결과")
    print("=" * 56)
    drive_ok = result.get("ok")
    for line in result.get("log", []):
        print("  " + line)
    print(f"\nRAF 생존: G.t {t0:.3f} -> {t1:.3f}  ({'OK 증가' if t1 > t0 else 'FAIL 정지!'})")
    print(f"콘솔 에러/경고: {len(console_errors)}")
    for e in console_errors: print("   - " + e)
    print(f"페이지 예외(throw): {len(page_errors)}")
    for e in page_errors: print("   - " + e)

    failed = (not drive_ok) or (t1 <= t0) or console_errors or page_errors
    if not drive_ok:
        print(f"\n드라이브 실패 지점: {result.get('where')} — {result.get('msg')}")
    print("\n" + ("RESULT: FAIL" if failed else "RESULT: PASS"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
