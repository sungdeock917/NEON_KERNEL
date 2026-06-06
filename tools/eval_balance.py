#!/usr/bin/env python3
"""NEON KERNEL 기체×코어 밸런스 eval (Playwright / Python)

"같은 코어, 다른 기체"(정의서 8장)를 데이터로 검증한다.
엔진의 실제 필터 applyChassisToCore() 를 통과시킨 코어의 사격 스탯을 직접 읽어
기체별 화력 변형을 측정한다. 거동(behavior)은 기체가 안 바꾸므로(물리 파라미터만 왜곡)
raw 처리량 = strands × dmg / interval 이 기체 간 비교의 정공법.

  python tools/eval_balance.py
"""
import sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "prototype" / "index.html"

# 엔진 안에서 기체×코어 필터 스탯을 수집
COLLECT = r"""
() => {
  const out = { chassis: CHASSIS.map(c => c.short), t1: [], t2: [] };
  const readCore = (mk) => {
    const rows = [];
    let behavior = null, bp = null;
    for (let ci = 0; ci < CHASSIS.length; ci++) {
      setChassisIndex(ci);
      if (CHASSIS[ci].id === 'gwanglan') G.gwanglanStacks = 0; // 스택0 기준
      const c = mk();
      behavior = c.behavior; bp = c.bparams || {};
      rows.push({ strands: c.strands, dmg: +c.dmg.toFixed(4), interval: +c.interval.toFixed(4),
                  bulletR: +c.bulletR.toFixed(2), speed: Math.round(c.speed), life: +c.life.toFixed(3),
                  rawDPS: +(c.strands * c.dmg / c.interval).toFixed(2),
                  range: Math.round(c.speed * c.life) });
    }
    return { rows, behavior, bp };
  };
  for (const s of T1_CORES) { const r = readCore(() => makeT1Id(s.id));
    out.t1.push({ id: s.id, name: s.name, attr: s.attr, behavior: r.behavior, bp: r.bp, rows: r.rows }); }
  for (const s of T2_CORES) { const r = readCore(() => makeT2FromIds(s.parents[0], s.parents[1]));
    out.t2.push({ id: s.id, name: s.name, attr: s.attr, behavior: r.behavior, bp: r.bp, rows: r.rows }); }
  // 광랜 스택 성장 샘플: streamPing 기준 스택 0/3/6 interval
  setChassisIndex(out.chassis.indexOf('광랜'));
  const gw = [];
  for (const st of [0, 3, 6]) { G.gwanglanStacks = st; const c = makeT1Id('streamPing');
    gw.push({ stacks: st, interval: +c.interval.toFixed(4), rawDPS: +(c.strands*c.dmg/c.interval).toFixed(2) }); }
  out.gwanglan_stacks = gw;
  setChassisIndex(0);
  return out;
}
"""

# 글리치 듀티사이클: 사격 1/0.45초 → 과열 → 0.75초 정지 반복
GLITCH_DUTY = (1/0.45) / ((1/0.45) + 0.75)
# 딥웹 룰렛 EV (압축 결과 1회당 dps 배율): jackpot .2 / normal .5 / curse .3
DEEPWEB_EV = 0.2*(1.6*1.5/0.82) + 0.5*1.0 + 0.3*(0.6/1.25)


def bar(v, vmax, width=10):
    n = int(round(v / vmax * width)) if vmax else 0
    return "█" * n + "·" * (width - n)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(INDEX.as_uri())
        pg.wait_for_function("typeof G !== 'undefined' && G && G.t >= 0", timeout=8000)
        data = pg.evaluate(COLLECT)
        b.close()

    ch = data["chassis"]  # ['레거시','프록시','광랜','글리치','딥웹']
    gi = ch.index("글리치")

    def channel(behavior, bp, interval):
        """기체 배율이 안 먹는 거동 데미지 채널(단일표적 지속). bparams는 chassis 미스케일."""
        g = lambda k: bp.get(k) or 0
        if behavior == "dot":   return g("dotDps")
        if behavior == "area":  return g("puddleDps") * min(1, (g("puddleTime") or interval) / interval)
        if behavior == "beam":  return g("beamDmgps") + g("dotDps")
        if behavior == "hold":  return g("holdDps") * min(1, (g("holdTime") or interval) / interval)
        if behavior == "burst": return g("burstDmg") / interval        # ≈1 파편/발(근사)
        if behavior == "fragment": return g("fragDmg") / interval      # ≈1 파편(근사)
        return 0.0

    def eff_row(core):
        """effDPS = 직격 throughput(기체스케일) + 거동채널(기체불변). 글리치는 듀티 보정."""
        rows, beh, bp = core["rows"], core["behavior"], core["bp"]
        e = []
        for j, r in enumerate(rows):
            v = r["rawDPS"] + channel(beh, bp, r["interval"])
            if j == gi:
                v *= GLITCH_DUTY
            e.append(round(v, 2))
        return e

    def chassis_invariance(core):
        """effDPS 중 기체불변 채널이 차지하는 비율(레거시 기준). 1.0에 가까울수록 기체 무의미."""
        r0 = core["rows"][0]
        eff = r0["rawDPS"] + channel(core["behavior"], core["bp"], r0["interval"])
        chn = channel(core["behavior"], core["bp"], r0["interval"])
        return (chn / eff) if eff else 0.0

    print("=" * 80)
    print("NEON KERNEL — 기체×코어 밸런스 eval")
    print("  effDPS = 직격(strands×dmg/interval, 기체스케일) + 거동채널(dot/puddle/beam/hold, 기체불변)")
    print("=" * 80)
    print("기체별 필터 요약:")
    print("  레거시 = 표준(기준)  |  프록시 = 탄 크기3×·속도0.3×·지속4.5×(rawDPS 동일, 거대탄→다중히트 실효↑)")
    print(f"  광랜 = 탄3×·dmg0.26×(+압축스택 연사복리)  |  글리치 = dmg0.82×·간격1.08×, 듀티 {GLITCH_DUTY:.1%}(정지반복)")
    print(f"  딥웹 = 전체 +8%dmg·-2%간격, 압축결과 룰렛EV ×{DEEPWEB_EV:.2f}(분산 0.48~2.93)")
    print()

    def table(title, cores, band_ref):
        hdr = f"{title:<18}" + "".join(f"{c:>8}" for c in ch) + "   거동"
        print(hdr); print("-" * len(hdr))
        effs = []
        for core in cores:
            e = eff_row(core)
            effs.append(e)
            inv = chassis_invariance(core)
            tag = core["behavior"]
            mark = f"  {tag}" + (f" ⚠기체불변{inv:.0%}" if inv >= 0.5 else "")
            nm = f"{core['name']}"
            print(f"{nm:<18}" + "".join(f"{v:>8.2f}" for v in e) + mark)
        flat = [v for row in effs for v in row]
        print(f"\n  {title} effDPS 밴드: {min(flat):.1f} ~ {max(flat):.1f}  ({band_ref})")
        return effs

    t1eff = table("T1 코어", data["t1"], "CLAUDE.md 기준선 T1 2~10")
    print()
    t2eff = table("T2 코어", data["t2"], "CLAUDE.md 기준선 T2 7~22")

    # --- 기체별 평균 배율(레거시 대비) ---
    print("\n" + "=" * 80)
    print("기체별 실효DPS 평균 배율 (레거시=1.00 기준, T1+T2 전체 평균)")
    print("-" * 80)
    alleff = t1eff + t2eff
    base_avg = sum(r[0] for r in alleff) / len(alleff)
    for j, c in enumerate(ch):
        avg = sum(r[j] for r in alleff) / len(alleff)
        mult = avg / base_avg
        print(f"  {c:<6} 평균 {avg:6.2f}  ×{mult:.2f}  {bar(mult, 1.5)}")
    print("  * 프록시 배율=레거시 동일(rawDPS만 반영). 거대탄 다중히트·보호막 미반영 → 실전 체감은 더 높음")
    print("  * 딥웹은 위 base에 압축결과마다 룰렛 ×0.48~2.93(EV {:.2f}) 추가 변동".format(DEEPWEB_EV))

    # --- ⚠ 설계 발견: 거동딜 코어의 기체 불변성 ---
    print("\n" + "=" * 80)
    print("⚠ 설계 발견: 기체 필터가 거동 데미지 채널(bparams)을 스케일하지 않음")
    print("-" * 80)
    print("  applyChassisToCore는 dmg/strands/interval/speed/bulletR/life만 왜곡 → bparams(dot/puddle/")
    print("  beam/hold/burst/frag 딜)는 5기체 동일. 주력딜이 거동인 코어는 '같은 코어 다른 기체'가 약화:")
    flagged = [(c, chassis_invariance(c)) for c in data["t1"] + data["t2"] if chassis_invariance(c) >= 0.5]
    flagged.sort(key=lambda x: -x[1])
    for c, inv in flagged:
        print(f"    - {c['name']:<14} ({c['behavior']:<8}) 기체불변 비중 {inv:.0%}")
    if not flagged:
        print("    (해당 없음)")

    # --- 광랜 스택 성장 ---
    print("\n광랜 압축스택 → 연사 복리 (streamPing 기준):")
    for g in data["gwanglan_stacks"]:
        print(f"  stack {g['stacks']}: interval {g['interval']:.4f}s  rawDPS {g['rawDPS']:.2f}")


if __name__ == "__main__":
    main()
