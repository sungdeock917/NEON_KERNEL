#!/usr/bin/env python3
"""NEON KERNEL 보스 HP/밸런스 eval (Playwright / Python)

실제 엔진을 헤드리스로 돌려 보스별 TTK(처치 시간)·달성 DPS·피해량을 측정한다.
모델 추정이 아니라 진짜 collide/방패/테두리/물량이 도는 실측 → 보스 HP 튜닝 근거.

  python tools/eval_boss.py

측정 모드: 자동회전(스윕) 기준선 — 브레이크 위상정렬(핵심 스킬)을 안 쓴 '하한 화력'.
  실제 숙련 플레이는 더 빠름(정렬=폭딜). 즉 TTK_sweep는 사실상 상한(가장 느린 케이스).
플레이어는 무적(hpMax 1e9)으로 두어 끝까지 측정, 피해량은 위협 지표로 별도 수집.
"""
import sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "prototype" / "index.html"

# 섹터별 '적정 진척' 대표 빌드(정의서 11.2 요구 성장)와 보스 측정
COLLECT = r"""
() => {
  try { localStorage.clear(); } catch (e) {}
  SAVE = defaultSave(); currentChassisIndex = 0;
  const COLS = ['mint', 'red', 'purple', 'grey'];
  function buildLoadout(slots, tiers) {
    SAVE.slots = slots; SAVE.chassis = 'legacy'; currentChassisIndex = 0;
    newGame();
    G.hpMax = 1e9; G.hp = 1e9; // 무적 — 끝까지 측정
    const order = SLOT_UNLOCK_ORDER.slice(0, slots);
    for (let i = 0; i < order.length; i++) {
      const t = tiers[i], c = COLS[i % 4];
      let core;
      if (t === 'T3') core = makeCore(3, [c, COLS[(i + 1) % 4]]);
      else if (t === 'T2') core = makeT2OfColor(c);
      else core = makeT1Id(T1_BY_COLOR[c][0]);
      G.slots[order[i]] = core;
    }
    reapplyChassisToAllCores();
  }
  // 이론 최대 DPS(모든 코어가 표적에 명중 = 브레이크 정렬 이상치) — 직격+거동채널 근사
  function coreDPS(c) {
    const bp = c.bparams || {};
    let dps = c.strands * c.dmg / c.interval;
    const g = k => bp[k] || 0;
    if (c.behavior === 'dot') dps += g('dotDps');
    else if (c.behavior === 'area') dps += g('puddleDps');
    else if (c.behavior === 'beam') dps += g('beamDmgps') + g('dotDps');
    else if (c.behavior === 'hold') dps += g('holdDps');
    return dps;
  }
  function measure(w, slots, tiers) {
    buildLoadout(slots, tiers);
    const idealDPS = G.slots.reduce((s, c) => s + (c ? coreDPS(c) : 0), 0);
    startWave(w);
    const hp0 = G.boss.hpMax;
    const dt = 1 / 60; let t = 0, ttk = null;
    for (let f = 0; f < 60 * 50; f++) { // 최대 50초
      update(dt); t += dt;
      if (!G.boss) { ttk = t; break; }
    }
    const dmgTaken = Math.round(1e9 - G.hp);
    return { w, kind: BOSS_WAVES[w], hp0, slots, tiers: tiers.join('/'),
             idealDPS: +idealDPS.toFixed(1), ttkIdeal: +(hp0 / idealDPS).toFixed(1),
             ttkSweep: ttk ? +ttk.toFixed(1) : null, achievedDPS: ttk ? +(hp0 / ttk).toFixed(1) : 0,
             dmgTaken };
  }
  return [
    measure(10, 3, ['T2', 'T1', 'T1']),
    measure(20, 5, ['T3', 'T2', 'T2', 'T1', 'T1']),
    measure(30, 6, ['T3', 'T3', 'T2', 'T2', 'T2', 'T1']),
  ];
}
"""


def assess(r):
    if r["ttkSweep"] is None:
        return "⚠ 50초 내 미처치 — 너무 단단/사거리 문제"
    s = r["ttkSweep"]
    if s < 5:   return "너무 물렁(스윕만으로 즉살)"
    if s > 40:  return "⚠ 스윕 기준 과도(정렬 강제 — 의도면 OK)"
    return "적정 밴드(스윕 5~40s)"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(INDEX.as_uri())
        pg.wait_for_function("typeof SAVE !== 'undefined' && typeof newGame === 'function'", timeout=8000)
        rows = pg.evaluate(COLLECT)
        b.close()

    print("=" * 84)
    print("NEON KERNEL — 보스 HP/밸런스 eval (레거시 기체, 자동회전 스윕 실측)")
    print("  TTK_ideal = HP / 이론최대DPS(전 코어 명중=브레이크 정렬 이상치, 하한 TTK)")
    print("  TTK_sweep = 자동회전 실측(정렬 스킬 0 = 상한 TTK). 실제 플레이는 둘 사이.")
    print("=" * 84)
    hdr = f"{'보스':<16}{'HP':>6}{'빌드':>14}{'이상DPS':>9}{'TTK이상':>9}{'TTK스윕':>9}{'피해입음':>9}  평가"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        sweep = f"{r['ttkSweep']:.1f}s" if r["ttkSweep"] is not None else ">50s"
        print(f"{r['kind']:<14}{r['hp0']:>6}{r['tiers']:>16}{r['idealDPS']:>9.1f}"
              f"{r['ttkIdeal']:>8.1f}s{sweep:>9}{r['dmgTaken']:>9}  {assess(r)}")
    print("\n해석 가이드:")
    print("  · TTK_ideal이 너무 짧으면(<3s) 보스가 정렬 한 방에 녹음 → HP↑ 여지.")
    print("  · TTK_sweep가 >40s/미처치면 스윕만으론 못 잡음 → 정렬·노바 강제(의도) 또는 사거리/HP 재조정.")
    print("  · 피해입음 = 무적 상태 누적 피격량(위협 지표). 클수록 생존 압박 큼.")
    print("  · ⚠ KERNEL_PANIC은 탄이 테두리에 닿아야 피해 → 단사거리 코어 빌드는 TTK 급증(사거리 게이트).")


if __name__ == "__main__":
    main()
