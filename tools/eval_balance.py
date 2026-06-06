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
                  range: Math.round(c.speed * c.life),
                  bp: { ...(c.bparams || {}) } });  // 기체별 bparams 스냅샷(이제 dmg채널이 기체스케일됨)
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


# Affix × 코어 수집 — 레거시 기체 고정(기체 영향 배제), 대표 코어 4종에 affix 적용 후 스탯/플래그
COLLECT_AFFIX = r"""
() => {
  setChassisIndex(0); // 레거시 = 기체 배율 1.0
  const beamSpec = T2_CORES.find(s => s.behavior === 'beam');
  const make = {
    '스트림핑(직격)': () => makeT1Id('streamPing'),
    '헤비정크(넉백)': () => makeT1Id('heavyJunk'),
    '도트스니펫(dot)': () => makeT1Id('dotSnippet'),
    '오버히트레이저(beam)': () => makeT2FromIds(beamSpec.parents[0], beamSpec.parents[1]),
  };
  const specs = [{ label: '(없음)', spec: null, kind: 'base' }];
  for (const id of AFFIX_PREFIX) specs.push({ label: AFFIX_BY_ID[id].name, spec: { prefix: id }, kind: 'prefix' });
  for (const id of AFFIX_SUFFIX) specs.push({ label: AFFIX_BY_ID[id].name, spec: { suffix: id }, kind: 'suffix' });
  for (const id of AFFIX_NEG) specs.push({ label: AFFIX_BY_ID[id].name, spec: { suffix: id }, kind: 'neg' });
  specs.push({ label: '거대한+치명적인', spec: { prefix: 'giant', suffix: 'crit' }, kind: 'combo' });
  specs.push({ label: '다중의+가속의', spec: { prefix: 'multi', suffix: 'accel' }, kind: 'combo' });
  const refs = Object.keys(make);
  const rows = [];
  for (const s of specs) {
    const cells = {};
    for (const rn of refs) {
      const c = make[rn](); setAffixes(c, s.spec);
      cells[rn] = { behavior: c.behavior, strands: c.strands, dmg: +c.dmg.toFixed(4), interval: +c.interval.toFixed(4),
                    bp: { ...(c.bparams || {}) }, fx: { ...(c.affixFx || {}) } };
    }
    rows.push({ label: s.label, kind: s.kind, cells });
  }
  return { refs, rows };
}
"""


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(INDEX.as_uri())
        pg.wait_for_function("typeof G !== 'undefined' && G && G.t >= 0", timeout=8000)
        data = pg.evaluate(COLLECT)
        affix = pg.evaluate(COLLECT_AFFIX)
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
        """effDPS = 직격 throughput(기체스케일) + 거동채널(이제 dmg채널은 기체스케일). 글리치 듀티 보정."""
        rows, beh = core["rows"], core["behavior"]
        e = []
        for j, r in enumerate(rows):
            v = r["rawDPS"] + channel(beh, r["bp"], r["interval"])  # 행별 bparams 사용
            if j == gi:
                v *= GLITCH_DUTY
            e.append(round(v, 2))
        return e

    def chassis_spread(core):
        """레거시 대비 거동코어의 기체별 effDPS 변동폭(최대/최소). 1.0이면 기체 무의미."""
        e = eff_row(core)
        return (max(e) / min(e)) if min(e) else 0.0

    print("=" * 80)
    print("NEON KERNEL — 기체×코어 밸런스 eval")
    print("  effDPS = 직격(strands×dmg/interval) + 거동채널(dot/puddle/beam/hold)  ※둘 다 기체 dmg배율 적용")
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
            nm = f"{core['name']}"
            print(f"{nm:<18}" + "".join(f"{v:>8.2f}" for v in e) + f"  {core['behavior']}")
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

    # --- ✅ 검증: 거동딜 코어가 이제 기체에 반응하는가 (bparams 스케일 적용 후) ---
    print("\n" + "=" * 80)
    print("✅ 거동딜 코어 기체 반응 회복 검증 (effDPS 변동폭 = 최대기체/최소기체)")
    print("-" * 80)
    print("  before: 거동코어는 기체 무관(변동폭 ≈1.0). after: 직격코어와 동일하게 기체에 반응해야 함.")
    BEH = ["dot", "area", "beam", "hold", "burst", "fragment"]
    behcores = [c for c in data["t1"] + data["t2"] if c["behavior"] in BEH]
    for c in sorted(behcores, key=lambda x: -chassis_spread(x)):
        sp = chassis_spread(c)
        e = eff_row(c)
        print(f"    - {c['name']:<14} ({c['behavior']:<8}) 변동폭 ×{sp:.2f}  "
              f"[레거시 {e[0]:.1f} ~ 글리치 {e[gi]:.1f}]")
    # 직격 코어 변동폭 기준(같은 폭이어야 정상)
    proj = [c for c in data["t1"] + data["t2"] if c["behavior"] not in BEH]
    if proj:
        avg_proj = sum(chassis_spread(c) for c in proj) / len(proj)
        print(f"\n  직격 코어 평균 변동폭 ×{avg_proj:.2f} (기준). 거동코어가 이 값에 수렴하면 '같은 코어 다른 기체' 회복.")

    # --- 광랜 스택 성장 ---
    print("\n광랜 압축스택 → 연사 복리 (streamPing 기준):")
    for g in data["gwanglan_stacks"]:
        print(f"  stack {g['stacks']}: interval {g['interval']:.4f}s  rawDPS {g['rawDPS']:.2f}")

    # ========================== Affix × effDPS ==========================
    def affix_effdps(cell):
        """Affix 적용 후 단일표적 effDPS. 스탯affix=엔진스탯반영, 온히트affix=EV 모델(실구현과 일치)."""
        direct = cell["strands"] * cell["dmg"] / cell["interval"]   # 직격 throughput
        chan = channel(cell["behavior"], cell["bp"], cell["interval"])  # 거동채널(DoT/beam 등)
        fx = cell.get("fx") or {}
        # 치명적인·분열의 = 직격 명중에만 (beam은 직격 dmg=0이라 자연히 무효 — 실구현과 일치)
        if fx.get("crit"):
            direct *= 1 + fx["crit"]["chance"] * (fx["crit"]["mult"] - 1)
        if fx.get("affixFrag"):
            af = fx["affixFrag"]
            direct += cell["dmg"] * af["frags"] * af["dmgRatio"] * 0.5 / cell["interval"]
        dps = direct + chan
        if fx.get("vulnOnHit"):                                 # 포맷팅: 적 장갑파괴(beam 포함 모든 피해↑)
            dps *= fx["vulnOnHit"]
        return dps  # drain(흡수=생존)·ddos(시야)는 effDPS 무관

    print("\n" + "=" * 80)
    print("Affix × effDPS (레거시 기체 고정, 단일표적). 셀=effDPS, 괄호=무affix 대비 배율")
    print("  ※ 스탯affix는 엔진 실측, 온히트affix(치명/포맷팅/분열)는 EV 모델 / 흡수·디도스는 effDPS 무관(별도)")
    print("-" * 80)
    refs = affix["refs"]
    base = {rn: affix_effdps(affix["rows"][0]["cells"][rn]) for rn in refs}  # (없음) 행
    shortref = [r.split("(")[0] for r in refs]
    hdr = f"{'Affix':<16}" + "".join(f"{s:>12}" for s in shortref) + "   종류"
    print(hdr); print("-" * len(hdr))
    for row in affix["rows"]:
        cellstr = ""
        for rn in refs:
            v = affix_effdps(row["cells"][rn])
            mult = v / base[rn] if base[rn] else 0
            cellstr += f"{v:>6.1f}(×{mult:.2f})"[:12].rjust(12)
        note = ""
        if row["label"] in ("흡수의",):  note = "  (생존, DPS 무관)"
        if row["label"] in ("디도스",):  note = "  (시야 debuff)"
        print(f"{row['label']:<16}" + cellstr + f"   {row['kind']}{note}")
    print("\n  · 거대한이 beam(오버히트레이저)의 beamDmgps도 키우는지 = bparam 일관성 확인 포인트")
    print("  · 마이너스(랜섬웨어)는 ×<1, 디도스는 DPS 1.00(시야만 방해)")


if __name__ == "__main__":
    main()
