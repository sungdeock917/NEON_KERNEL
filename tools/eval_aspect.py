#!/usr/bin/env python3
"""NEON KERNEL 화면비 정규화(B+속도 하이브리드) eval — 방향별 균일성 실측.

모바일 세로/태블릿 가로 등 화면비가 달라도 방향별 경험이 균일한지 실제 엔진으로 검증.
  ① 반응시간: 적이 화면에 보인 뒤 중심까지 도달하는 시간(방어 반응 창). velScale(적 속도) 검증.
  ② 탄 도달시간: 플레이어 탄이 화면경계까지 가는 시간(요격 타이밍/사거리). velScale(플레이어 탄) 검증.
방향 간 격차(max/min)가 1에 가까울수록 균일. 기기 간 절대값이 비슷할수록 패리티(고정 Rref).

  python tools/eval_aspect.py
"""
import sys, io, pathlib, math, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "prototype" / "index.html"

# 페이지 안에서 방향별 반응시간 + 탄 도달시간을 실측
MEASURE = r"""
() => {
  SAVE = defaultSave(); SAVE.chassis = 'legacy'; SAVE.slots = 6; startGame();
  const dirs = [0, 45, 90, 135, 180, 225, 270, 315];
  const dt = 1 / 60;

  // ① 반응시간: 적을 방향 deg로 스폰, 사격/웨이브 정지, 무적. 화면진입~중심도달 시간.
  // ⚠ 테스트 적이 죽는 순간 웨이브 클리어 게이트가 다음 웨이브를 스폰 → 전역 count 대기는 오염됨.
  //   → startWave 차단 + 테스트 적 '개체'를 추적(전역 아님).
  const origStartWave = startWave;
  function reactTime(deg) {
    const ang = deg * Math.PI / 180;
    startWave = () => {}; // 측정 중 웨이브 리스폰 차단
    G.enemies.length = 0; G.bullets.length = 0; G.ebullets.length = 0; G.warnings.length = 0;
    G.waveActive = false; G.spawnTimer = 1e9; G.hpMax = 1e9; G.hp = 1e9;
    for (let i = 0; i < 6; i++) G.slots[i] = null; // 사격 없음(적 방해 X)
    doSpawn(ang, ENEMY.runner);
    const me = G.enemies[G.enemies.length - 1]; me.hp = 1e9;
    let tVis = null, t = 0, out = null;
    for (let f = 0; f < 60 * 25; f++) {
      if (!G.enemies.includes(me)) { out = (tVis === null ? null : +(t - tVis).toFixed(3)); break; } // 충돌 제거 = 중심 도달
      if (tVis === null && me.x >= 0 && me.x <= W && me.y >= 0 && me.y <= H) tVis = t;
      update(dt); t += dt;
    }
    startWave = origStartWave;
    return out;
  }

  // ② 탄 도달시간: 슬롯0을 deg로 조준(브레이크 고정), 발사 → 탄속으로 경계 도달시간 = edge/|v|.
  function bulletReach(deg) {
    const ang = deg * Math.PI / 180;
    newGame(); G.slots = [makeT1Id('streamPing'), null, null, null, null, null];
    reapplyChassisToAllCores();
    G.rot = ang; G.braking = true; G.bullets.length = 0;
    fireSlot(0);
    const b = G.bullets.find(x => x.behavior !== 'beam');
    if (!b) return null;
    const sp = Math.hypot(b.vx, b.vy);
    const c = Math.abs(Math.cos(ang)), s = Math.abs(Math.sin(ang));
    const edge = Math.min(c > 1e-6 ? (W / 2) / c : 1e9, s > 1e-6 ? (H / 2) / s : 1e9);
    return +(edge / sp).toFixed(3);
  }

  const react = {}, reach = {};
  for (const d of dirs) { react[d] = reactTime(d); reach[d] = bulletReach(d); }
  return { W, H, react, reach };
}
"""

DEVICES = [
    ("폰 세로",      390, 844),
    ("태블릿 가로",  1180, 820),
    ("정사각(기준)",  800, 800),
]


def stats(d):
    vals = [v for v in d.values() if v is not None]
    if not vals:
        return (None, None, None)
    return (min(vals), max(vals), max(vals) / min(vals))


def main():
    rows = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        for name, W, H in DEVICES:
            pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            pg.goto(INDEX.as_uri())
            pg.wait_for_function("typeof SAVE!=='undefined' && typeof startGame==='function'", timeout=8000)
            r = pg.evaluate(MEASURE)
            r["name"] = name
            rows.append(r)
            pg.close()
        b.close()

    print("=" * 78)
    print("NEON KERNEL — 화면비 정규화(B+속도) 방향별 균일성 eval")
    print("  반응시간 = 적 화면진입~중심도달(s). 탄도달 = 플레이어 탄이 경계까지(s).")
    print("  격차 = 방향 max/min (1=완전 균일). 기기 간 값이 비슷할수록 패리티.")
    print("=" * 78)
    def cell(d, deg):
        v = d.get(str(deg), d.get(deg))
        return f"{deg}°:{v:.2f}" if v is not None else f"{deg}°:--"
    for r in rows:
        rmin, rmax, rratio = stats(r["react"])
        bmin, bmax, bratio = stats(r["reach"])
        print(f"\n[{r['name']}]  {r['W']}x{r['H']} (비율 {r['W']/r['H']:.2f})")
        rr = "  ".join(cell(r["react"], d) for d in [0, 45, 90, 135])
        print(f"  반응시간(0~135°): {rr}   …   격차 {rratio:.2f}×  (밴드 {rmin:.2f}~{rmax:.2f}s)")
        br = "  ".join(cell(r["reach"], d) for d in [0, 45, 90, 135])
        print(f"  탄 도달  (0~135°): {br}   …   격차 {bratio:.2f}×  (밴드 {bmin:.2f}~{bmax:.2f}s)")

    print("\n해석:")
    print("  · 격차가 1.0~1.2면 방향 불균형 해소(목표). 현재 폰 세로는 미보정 시 반응 2.16×였음.")
    print("  · 기기 간 반응시간 밴드가 겹치면 폰·태블릿 패리티(모바일이 더 불리하지 않음).")
    print("  · clamp(velClampLo~Hi)가 binding이면 극단 화면비에서 잔여 격차 남음 — reactRef/clamp로 조절.")


if __name__ == "__main__":
    main()
