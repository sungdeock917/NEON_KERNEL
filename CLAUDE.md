# Project NEON KERNEL — 작업 인계 문서

원버튼 모바일 로그라이트 슈팅 게임. 기체가 화면 중앙 고정, 6궤도 슬롯이 자동 회전·연사,
탁(회전반전)·꾹(브레이크) 단일 터치 조작. 텍스트 제로 네온 UI.

## 파일 위치
- **프로토타입(메인 작업물)**: `prototype/index.html` — 단일 HTML+Canvas, 의존성 0
- **게임 정의서(설계 마스터)**: `docs/NEON_KERNEL_정의서_최종판.md` — 모든 설계 결정의 근거
- **미리보기 서버**: `.claude/launch.json`의 `prototype` (python http.server 포트 4321)
  - node/npx 없으면 python 사용. `python -m http.server 4321 --directory prototype` 로도 실행 가능

## 검증 방식 (중요)
- 코드는 거의 전부 **eval 하네스로 게임 엔진에서 직접 측정/검증**하며 작업했다.
- **교훈: eval 검증 시 `update()`만 말고 `render()`도 매 프레임 돌려야 함** (렌더 크래시는 update-only 테스트로 안 잡힘 — 실제 RAF 정지 버그를 그렇게 놓친 적 있음).
- 미리보기(Claude Preview/브라우저)로 화면 확인 + 콘솔 에러 0 확인이 기본 루프.

### 자동 검증 하네스 (Playwright) — 코드 수정 후 필수 실행
- **`python tools/verify_game.py`** — 실제 Chromium으로 `prototype/index.html`을 띄워 자동 점검.
  - 이 환경엔 **node가 없어** JS Playwright 대신 **Python Playwright**를 쓴다(`pip install playwright` + `python -m playwright install chromium` 1회 설치 완료됨).
  - 점검 항목: ①콘솔 에러/경고 ②페이지 예외(throw) ③**RAF 생존**(`G.t` 증가 — 렌더 크래시면 RAF가 멈춰 G.t 정지 → 자동 검출. 위 교훈을 자동화).
  - 신규/주요 코드 경로(기체 5종 전환·압축 훅·딥웹 룰렛 3분기·저주 슬롯잠금·신규 렌더 분기)를 합성으로 강제 구동 후 라이브 입력까지 흘린다.
  - 종료코드 0=PASS / 1=FAIL. 옵션: `--headed`(창 표시), `--seconds N`(라이브 구동 시간).
  - **새 시스템 추가 시 `DRIVE_JS`에 그 경로 step을 추가**해 회귀 커버리지를 늘릴 것.
  - ⚠️ 구문 오류는 스크립트 전체 파싱을 죽여 게임이 백지가 된다(과거 `applyChassisToCore({...})` 닫는 `)` 누락 사례). 이 하네스가 그런 류를 즉시 잡는다.

## 씬 구조 (아웃게임 ↔ 인게임)
- **로드 시 `scene='main'`(아웃게임)으로 시작** — 더 이상 인게임이 곧바로 안 뜬다. `goScene`로 전환.
  씬: `main`/`select`/`upgrade`/`game`/`result`. `loop`가 game이면 `update+render`, 아니면 `renderMeta`.
- **G는 `startGame()`(=newGame+game씬) 때 생성** — 메타 화면에선 `G`가 undefined일 수 있다(메타 렌더는 `SAVE`만 참조).
  ⚠️ 검증/스크린샷 하네스는 `SAVE` 존재로 대기하고, 인게임 경로는 `startGame()`/`newGame()` 먼저 호출해야 함.
- **메뉴 조작 = 터치/클릭 버튼**(`metaButtons` 히트테스트). 키보드 테스트키는 `game` 씬에서만 동작.

## 조작 / 테스트 키
- **PC**: 마우스 클릭(또는 Space) — 짧게=탁(회전반전), 길게=꾹(브레이크/흡수확정). **(game 씬 한정)**
- **모바일**: 터치
- `R` 재시작 · `H` 안내토글
- `Enter` 정비궤도(합성) 즉시 진입 · `C` 후보 재추첨
- `B` 코어 시험장 토글 → `1~8` / `[ ]` T1 8종 코어 전환 (무적, 더미 스폰)
- `L` 해금 슬롯 수 3~6 순환 (아웃게임 슬롯 게이팅 시뮬레이션)

## 구현 완료 시스템
### 전투 코어 (검증·승인됨)
- 6궤도 자동회전·자동연사, 탁=회전반전, 꾹=브레이크(6방향 고정사격+과열드레인 1→3→5%)
- 오버히트 노바(과부하 후 떼는 순간 360도 충격파), 0.5초 무적, 체력 0~100 3구간 네온
- 360도 예고글로우→적 스폰, 적 4종(러너/바운서/슈터/실더), 예산 기반 웨이브, 투사체 상쇄
- 적 체력 웨이브 스케일링 `hpScale(w)`: 섹터1 ×1.0 → 섹터2 ×1.07~1.65 → 섹터3 ×1.8~3.0

### 코어/합성 (3티어 체계, 정의서 3·4·5·6장)
- **모델**: ATTR 4색(mint/red/purple/grey) + 코어는 `{tier, colors, behavior, bparams, ...}`.
  T1=`makeT1(spec)`, T2=`makeT2(spec)`, T3=`makeCore(3,colors,base,mat)`.
- **T1 8종**(`T1_CORES`, 정의서 6.1): straight/scatter/dot/area/pull/delay/knockback/fragment.
  거동별 탄 렌더 + 코어 실루엣(`drawCoreShape`)으로 시각 구분.
- **T2 12종**(`T2_CORES`+`T2_LOOKUP`, 정의서 6.2): 두 T1 서브타입 조합으로 룩업(순서무관).
  신규 거동: burst/beam/hold/bounce/shed. 융합 3종이 "부모 능력 결합".
- **T3 색조합 10종 효과**(`COMBO_FX`, 정의서 6.3): coreMod(동색 오버클록)/onHit(이종 합선).
  상태: `e.vuln`(장갑파괴), `e.held`(홀딩).
- **압축 알고리즘** `resolveCompression`/`canCompress`(정의서 3.3): T1+T1 동색→T2,
  T2+T2 색무관→T3, 반시계 베이스, 연쇄, 1수 앞보기 예외, 만석 덮어쓰기. 8케이스 eval 검증.
  단계 큐 애니메이션(`planCompression`→`updateMerge` slide→pop→pause)으로 합쳐지는 과정 표시.
- **혈통 글리프**(`drawCoreGlyph`): T1=단일형태 / T2=육각프레임+부모2형태 위성 / T3=회전아우라+듀얼색+부모위성.

### 정비 궤도 (보상, 정의서 3장)
- 페이즈 `combat`/`orbit`. 웨이브 클리어→정비궤도.
- **2단계 이산 선택**(회전정지): ①후보(탁=다음, 꾹=확정) → ②코어=슬롯선택/스탯강화=대상코어선택.
  (정의서 3.2 연속회전 역흡수는 폐기—정밀선택에 부적합. 이산선택으로 대체.)
- **유형 A/B**(정의서 3.5): A=완제품 코어, B=스탯 오버클록(`BOOSTS` 4종). 비율 섹터1 80:20→섹터3 40:60.
- **슬롯 게이팅**: `MAXSLOTS`/`G.maxSlots`(3~6). 해금순서 `SLOT_UNLOCK_ORDER=[0,2,4,1,3,5]`
  → 3슬롯=삼각형(0·2·4) 360도 균등. `cwOf`/`ccwOf`가 잠긴슬롯 건너뜀(삼각형도 압축 가능).
  슬롯이 T3 개수 통제(3슬롯=T3 1개, 6슬롯=2~3개).

### 기체 (하드웨어 필터, 정의서 8장) — 검증·완료
- **모델**: `CHASSIS` 5종(레거시/프록시/광랜/글리치/딥웹). 코어 로직 비침습 — `applyChassisToCore`가
  코어의 `_baseStats` 보존 후 기체 `applyCore`로 물리 파라미터만 왜곡. `makeCore/makeT1/makeT2` 모두 통과.
- **거동 데미지 채널도 스케일**: 기체 `dmg` 배율을 `DMG_BPARAMS`(dotDps/puddleDps/beamDmgps/holdDps/
  burstDmg/fragDmg)에도 적용(유틸=반경·힘·시간 제외). beam(`base.dmg=0`)은 probe로 배율 산출. → 거동딜 코어도
  "같은 코어 다른 기체"가 작동(eval: 변동폭 ≈1.0→1.9~4.2). bparam 스케일 안 하면 beam/dot/hold가 기체 무관해짐.
- **기체 훅**: `onCompressionSuccess`(applyMergeStep에서 호출) — 광랜=연사 복리 스택+`reapplyChassisToAllCores`,
  딥웹=`rollDeepweb`(대박20/중간50/저주30, 저주=`cursed` 플래그→`canCompress` 차단=슬롯 일시잠금).
  프록시=`absorbDamage`(보호막)+`brakeDrain`0, 글리치=`suppressFiring`(과열 정지)+과열→노바 전환.
- **시각**: 프록시 보호막 링 / 글리치 과열 플리커 / 딥웹 저주(붉은X)·대박(금빛) 마커.
- **테스트 키**: `Q`/`E` 순환, `1~5` 직접 선택(런 중 전환은 디버그용). 정식 선택은 아웃게임 예정.
- ⚠️ 딥웹 룰렛 대박/저주는 현재 스탯 잭팟/디버프 임시구현 — 정식은 Affix(6.4) 연동 필요.

### Affix 모듈 (변이 코어, 정의서 6.4) — MVP 완료
- **모델**: `AFFIXES`(접두5·접미5·마이너스2), `core.affixes={prefix,suffix}`. 합성 순서 **base→Affix→기체**(멱등).
  `applyAffixesToBase`(stat 변형)가 기체 앞 레이어. `computeAffixFx`→`core.affixFx`(온히트/렌더 플래그).
- **접두(형태)**: 거대한/궤도의/다중의/관통의/분열의. **'유도의'(homing)는 폐기**(유도 미사용 확정과 충돌, 다중의로 대체).
- **접미(효과)**: 치명적인/가속의/과부하/포맷팅(`e.vuln` 재사용)/흡수의. **마이너스**: 디도스(시야가림)/랜섬웨어(스탯디버프).
- **온히트 배선**: `fireSlot`이 `affixFx`를 탄에 전파(`tagAffix`)→`collide`에서 crit/vulnOnHit/affixFrag/lifesteal 처리.
  dmg 총배율(Affix×기체)이 거동채널(bparams)에도 적용 — beam(base.dmg=0)은 probe 경로.
- **획득 = 유형C 모듈 보상**(사용자 확정, 정의서 6.4 '모듈' 프레임): 정비궤도 후보에 모듈 등장 → 대상 코어 선택(유형B 흐름 재사용)
  → `addAffix`로 단일 슬롯 부착. **변이코어 통째 드롭은 딥웹/제로데이 전용**. 마이너스 affix는 모듈 보상 제외(딥웹 저주 전용).
- **T3 한정**(사용자 확정): 등장 조건 = **T3 코어 장착 중**(`hasT3`, 22%), 부착 대상 = **T3 코어만**(`affixableSlots`).
  T3 천장 이후 강화 영역(정의서 3.3/6.3). `stepSlots`가 pickedAffix면 T3목록 반환 → 렌더·탁·확정 일관.
- **모듈 명칭 = 형태(접두)/효과(접미)**(사용자 확정): 라벨에 'Affix' 대신 `형태`·`효과`(정의서 6.4 분류, 위치 아닌 기능 전달).
  `rollCandidates`/`orbitConfirm`/`drawAffixModuleIcon`/`candInfo`.
- **시각**: 변이 글리프 마커(금빛/붉은 헤일로+접두/접미 핍), DDoS 화면 오버레이. **테스트키 `A`**=장착코어 Affix 순환.
- ⚠️ MVP라 정식 풀(10+10)은 미완. 필드 드롭/LV4 해금 미구현(현재 웨이브 게이트). 딥웹 연동 미배선(아래 참조).
- **밸런스 발견**(eval_balance.py): 다중의(strands+2)가 1가닥 직격코어를 ×3.0(콤보 ×3.85) — 아웃라이어, 15장 패스 1순위.
  거동의존(다중의 on beam=무효), 유틸affix(궤도의/관통의/흡수의)=단일표적 0DPS.

### SF 알림 (텍스트리스 재해석)
- "텍스트리스 = 긴 설명 지양이지 이름 은닉 아님"(사용자 확정). **이름만** 짧게(설명문 X), 기체 위 칩(이름+거동 글리프).
- **조준 팝업(`G.aimToast`, 지속)**: 정비궤도 cand 단계에서 **조준선이 향한 보상의 이름 + 한 줄 효과**(사용자 확정 — 부착 시가 아닌 조준 시).
  `rollCandidates`/`orbitTap`에서 `setAimToast`, 단계 전환/`finishMerge`에서 `clearAimToast`. `candInfo`가 코어/모듈/강화 → 이름·거동·색·desc.
  **설명 한 줄(desc)**: 코어=`core.fx`(거동 설명), Affix=`AFFIX.desc`(효과), 강화=`BOOST.desc`(수치). "이름만으론 성능 파악 어려움" 해소.
- **일시 토스트(`pushToast`/`G.toasts`)**: 조준으로 안 보이는 **합성 결과**(`applyMergeStep`)만. 글리치 인→홀드→페이드(~1.6초).
- 렌더 `drawToasts`(조준+일시 통합, `drawToastChip`). 획득/부착 시점 토스트는 제거(조준 팝업으로 대체).

### 아웃게임 (메타, 정의서 9장) — 풀 1차 완료
- **영속 `SAVE`(localStorage `neonkernel_save_v1`)**: 재화·슬롯(3~6)·피지컬레벨·시작부스트·기체·클리어여부·최고기록. `persist()`로 저장.
- **메인 화면**: 네온 로고 + 누적 재화 + `시작`/`기체 선택`/`강화` + 최고기록.
- **기체 선택**: 5기체 카드(아이콘·특성·선택/잠금). `chassisLocked`=딥웹은 `SAVE.cleared` 선행(8.2). 선택 시 `SAVE.chassis`.
- **강화(9.4)**: ①`SLOT_STEPS` 슬롯개방(재화+`best.wave` 진척조건) ②`PHYS_LIST` 4종(rot/hp/intercept/brake) ③`STARTBOOST`. `buySlot/buyPhys/buyStartBoost`.
- **정산(9.3)**: `endGame(cleared)` — 재화=웨이브×3+섹터보너스(10/20/30)+첫도달(신기록 점프)+T3×10. 최고기록 갱신.
- **인게임 연동 `metaRunMods()`**(newGame이 호출): `maxSlots`/`hpMax`/`rotMul`/`brakeMul`/`novaMul`/`interceptBonus`/`startCores`.
  적용 지점 — 회전 `rotMul`, 드레인 `brakeMul`, 노바 `novaMul`, hp클램프 `G.hpMax`, 브레이크관통 `interceptBonus`, 시작코어 수.
- **전환**: 사망(`die`→1.8s 또는 탭)·30방 클리어 → `endGame` → `result` 씬. `startGame`이 `SAVE.chassis`로 `currentChassisIndex` 설정.
- ⚠️ 미구현: 이어하기(9.5 보스전 부활), 링크 배치학(9.2), 슈퍼 정비궤도(3.7), 중간/최종 보스. intercept/brake 강화 밸런스 미측정.

### 코어 시험장 (`B` 키)
- T1 8종을 슬롯에 전부 장착해 손맛 비교. 무적, 더미 스폰.

## 밸런스 기준선 (회귀 주의)
- 전투 발사간격/적HP/위상정렬: "조작감 꽤 괜찮다" 승인됨(함부로 회귀 금지).
- T2 12종 단일DPS 밴드 7~22. T1 2~10, T3 15~91. "의도된 불균형"(정의서 8장) 내 역할 유지.
- 정밀 수치는 정의서 15장 8번 밸런싱 패스에서 일괄(현재는 CFG/TIER_STATS 상수로 분리).
- **기체별 평균 화력 배율**(레거시=1.00, `python tools/eval_balance.py`): 프록시 1.00(raw·실효↑) /
  광랜 0.69(단발↓·물량↑) / 글리치 0.57(평소 약함=노바 연료, 의도) / 딥웹 1.10(+룰렛 변동).
- ⚠️ **미해결 아웃라이어**: 브로드캐스트(T2 scatter) effDPS 56~62 → 기준선 7~22 크게 이탈.
  15장 밸런싱 패스 후보(지금 손대면 회귀 위험).

## 설계 확정 사항
- **T4 미추가**: T3가 천장(정의서 6.3). 후반 깊이 = 슬롯이 T3개수 통제 + 유형B 스탯펌핑 + Affix(6.4) + 기체.
- **유도(homing) 미사용**: 위상정렬 조준스킬과 충돌(사용자 결정). T1엔 원래 없음.
- 슬롯은 아웃게임 고정(런 내 미개방) → 아웃게임 성장·반복 게이트 보존.
- **기체 dmg 배율은 거동 데미지 채널(bparams)에도 적용**(2026-06 확정): 안 그러면 beam/dot/hold 코어가
  기체 무관해져 정의서 8장 "같은 코어 다른 기체" 정체성이 깨짐. 유틸 파라미터(반경·힘·시간)는 미스케일.
- **딥웹 대박 = Affix '품질 잡팟'**(2026-06 확정, 미배선): 가치를 "접근(access)"이 아닌 "품질/물량"으로 걸어야
  Affix 해금 후에도 의미 유지. 대박=필드보다 좋은 Affix(이중=글리치에러코어 비중↑·고굴림), 헤드라인은 제로데이(해금무관).
  → 딥웹 룰렛(현 스탯 임시구현)에 Affix 배선 시 이 방향으로. (Affix `setAffixes(core,'random'|'curse')` 재사용)

## 다음 작업 후보 (미정)
1. 고밀도·정예 적 가독성 (섹터3, 위상왜곡자·하드웨어크러셔)
2. 보스 3종 (정의서 11.1) + 중간/최종 보스전(정산·이어하기 연동)
3. Affix 확장 (정식 풀 10+10 + 필드 드롭/LV4 해금 + 딥웹 '품질 잡팟' 배선) — MVP는 완료
4. 아웃게임 잔여 (이어하기 9.5·링크 배치학 9.2·슈퍼 정비궤도 3.7) — 풀 1차는 완료
5. 밸런싱 패스 (정의서 15장) — 브로드캐스트·다중의 아웃라이어, intercept/brake 강화 곡선 일괄

## 작업 스타일 (사용자)
- 시스템 간 모순을 날카롭게 잡음. 결정 전 장단점·대안을 솔직히 제시하고, 사용자 확정 후 구현.
- 한 번에 하나씩 확정. 데이터/eval로 근거를 보이는 걸 선호.
