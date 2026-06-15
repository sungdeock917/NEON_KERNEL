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
      let core; // 결정적 코어(RNG 제거 — 재현 가능한 TTK)
      if (t === 'T3') core = makeCore(3, [c, COLS[(i + 1) % 4]]);
      else if (t === 'T2') core = makeT2FromIds(T1_BY_COLOR[c][0], T1_BY_COLOR[c][0]);
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
  function measure(w, slots, tiers, aligned) {
    buildLoadout(slots, tiers);
    const idealDPS = G.slots.reduce((s, c) => s + (c ? coreDPS(c) : 0), 0);
    startWave(w);
    let origDrain;
    if (aligned) { // 정렬(리듬) 모드: 예고 중 + 탄 비행 동안만 브레이크, 평소엔 스윕(실플레이 모델)
      origDrain = G.chassis.brakeDrain; // 공유 CHASSIS 객체 — 패치 후 원복(기체 스윕 확장 시 누수 방지)
      G.chassis.brakeDrain = () => 0;   // (brakeMul=0은 `|| 1` falsy 함정으로 무효 — 훅 패치가 정도)
      G.brakeTime = 1;
    }
    const hp0 = G.boss.hpMax;
    const dt = 1 / 60; let t = 0, ttk = null, holdT = 0, bossDied = false;
    const seen = new Map(); let sigReached = 0, sigStopped = 0; // 시그니처 탄: 도달 vs 요격 분리 추적
    // 보스탄 소멸을 '도달(중심<42px)' vs '요격(그 외)'로 분리. 단 killBoss는 G.ebullets를 일괄 청소하므로
    // 보스 사망 프레임의 잔존 탄은 어느 쪽도 아님(요격 오집계 방지) — bossDied 가드로 그 프레임 스윕을 건너뜀.
    for (let f = 0; f < 60 * 50; f++) {
      if (aligned) {
        // 리듬 플레이 봇: 방향형 예고(angs)만 정렬+브레이크, 수축 링(panic)은 스윕 유지가 정답
        // (링에 브레이크 걸면 격자 동결로 틈새 통과 — 실측으로 확인된 오답 플레이)
        const tele = G.boss && G.boss.tele;
        if (tele && tele.angs) { holdT = 1.9; G.rot = tele.angs[0]; }
        G.braking = holdT > 0; holdT -= dt;
      }
      update(dt); t += dt;
      if (!G.boss) { ttk = t; bossDied = true; break; } // 사망 프레임: 잔존 보스탄 집계 폐기
      const alive = new Set(G.ebullets);
      for (const [eb, d] of seen) {
        if (!alive.has(eb)) { if (d < 42) sigReached++; else sigStopped++; seen.delete(eb); }
      }
      for (const eb of G.ebullets) if (eb.boss) seen.set(eb, Math.hypot(eb.x - CX, eb.y - CY));
    }
    // 타임아웃(50s 미처치)으로 끝나면 seen에 남은 비행 탄은 도달/요격 불명 → 미집계(분모 왜곡 인지)
    if (aligned) G.chassis.brakeDrain = origDrain; // 원복(try/finally 대용 — evaluate 단일 경로)
    const dmgTaken = Math.round(1e9 - G.hp);
    return { w, kind: BOSS_WAVES[w], hp0, slots, tiers: tiers.join('/'),
             idealDPS: +idealDPS.toFixed(1), ttkIdeal: +(hp0 / idealDPS).toFixed(1),
             ttkSweep: ttk ? +ttk.toFixed(1) : null, achievedDPS: ttk ? +(hp0 / ttk).toFixed(1) : 0,
             dmgTaken, sigReached, sigStopped };
  }
  function measureBoth(w, slots, tiers) { // 스윕(정렬 스킬 0) vs 정렬(리듬 브레이크) — 신패턴 방어가능성 실측
    const s = measure(w, slots, tiers, false);
    const a = measure(w, slots, tiers, true);
    return { ...s, ttkAligned: a.ttkSweep, dmgAligned: a.dmgTaken,
             sigA: a.sigReached, sigAStop: a.sigStopped };
  }
  return [
    measureBoth(10, 3, ['T2', 'T1', 'T1']),
    measureBoth(20, 5, ['T3', 'T2', 'T2', 'T1', 'T1']),
    measureBoth(30, 6, ['T3', 'T3', 'T2', 'T2', 'T2', 'T1']),
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
    hdr = (f"{'보스':<14}{'HP':>6}{'빌드':>14}{'TTK이상':>8}{'TTK스윕':>8}{'TTK정렬':>8}"
           f"{'피해스윕':>9}{'피해정렬':>9}{'시그스윕':>10}{'시그정렬':>10}  평가")
    print(hdr); print("-" * len(hdr))
    for r in rows:
        sweep = f"{r['ttkSweep']:.1f}s" if r["ttkSweep"] is not None else ">50s"
        alig = f"{r['ttkAligned']:.1f}s" if r.get("ttkAligned") is not None else ">50s"
        sig_s = f"{r['sigReached']}/{r['sigReached'] + r['sigStopped']}"
        sig_a = f"{r['sigA']}/{r['sigA'] + r['sigAStop']}"
        print(f"{r['kind']:<12}{r['hp0']:>6}{r['tiers']:>16}{r['ttkIdeal']:>7.1f}s{sweep:>8}{alig:>8}"
              f"{r['dmgTaken']:>9}{r['dmgAligned']:>9}{sig_s:>10}{sig_a:>10}  {assess(r)}")
    print("\n해석 가이드:")
    print("  · TTK_ideal이 너무 짧으면(<3s) 보스가 정렬 한 방에 녹음 → HP↑ 여지.")
    print("  · TTK_sweep가 >40s/미처치면 스윕만으론 못 잡음 → 정렬·노바 강제(의도) 또는 사거리/HP 재조정.")
    print("  · 시그 = 시그니처(보스 텔레그래프) 탄 '도달/총' — 도달은 피격 또는 무적흡수, 나머지는 요격.")
    print("    시그정렬 도달 ≪ 시그스윕 도달 이면 '예고→정렬→요격' 루프가 수치로 성립.")
    print("  · 정렬 모드 = 리듬 플레이 봇(예고 중+비행 동안만 브레이크, 평소 스윕). 피해는 미니언 포함 총합.")
    print("  · ⚠ KERNEL_PANIC은 탄이 테두리에 닿아야 피해 → 단사거리 코어 빌드는 TTK 급증(사거리 게이트).")


if __name__ == "__main__":
    main()
