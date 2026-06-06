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
    step("globals-present", () => {
      for (const n of ["G","CHASSIS","setChassisIndex","rollDeepweb","canCompress",
                       "applyChassisToCore","reapplyChassisToAllCores","makeT1Id","newGame"]) {
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

    // 정상 상태로 리셋(라이브 구동이 정상 경로도 돌도록)
    step("reset", () => { setChassisIndex(0); newGame(); });
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
        page.wait_for_function("typeof G !== 'undefined' && G && G.t >= 0", timeout=8000)

        # 신규 코드 경로 강제 구동
        result = page.evaluate(DRIVE_JS)

        # RAF 생존 확인: G.t 가 시간이 지나며 증가해야 한다(렌더 크래시면 멈춤)
        t0 = page.evaluate("G.t")
        time.sleep(args.seconds)
        # 라이브 구동 중 실제 입력도 몇 번 흘려 update/render 경로 자극
        for code in ["Space", "Space", "Enter"]:
            page.dispatch_event("body", "keydown", {"code": code}) if False else None
        page.keyboard.press("Space")     # 탁(회전 반전)
        page.keyboard.down("Space"); time.sleep(0.4); page.keyboard.up("Space")  # 꾹(브레이크)
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
