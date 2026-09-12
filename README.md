# Institutional Rotation Proxy Engine

미국 주식시장의 **섹터 로테이션과 시장 참여도**를 일별 가격, 거래량, 상대강도, 시장 폭(breadth), 크로스에셋 지표로 추정하는 Python/Dash 대시보드입니다.

> 이 프로젝트는 기관의 실제 매수·매도 주문이나 ETF 설정·환매 자금을 직접 측정하지 않습니다. 화면에 표시되는 수급 및 방향성 거래대금은 시장 데이터를 바탕으로 만든 **프록시(proxy)**이며, 투자 판단을 위한 참고 자료로만 사용해야 합니다.

## 주요 기능

- 반도체, AI, 소프트웨어, 사이버 보안, 전력, 방산 섹터 모니터링
- 섹터 ETF와 주요 지수의 상대강도 추적
- 최근 거래량 급증 및 분배일(distribution day) 프록시 계산
- 52주 고가·저가 근접 종목과 50일·200일 이동평균 상회 비율 분석
- 공식 ETF 편입 종목 기반 동일가중·ETF 비중가중 시장 폭 계산
- 20일·60일 상대수익률, 시장 폭, 거래량을 결합한 섹터 로테이션 점수
- 방향성 거래대금과 ETF 주요 편입 종목 리더십 표시
- 5개 크로스에셋 신호를 이용한 `RISK-ON` / `NEUTRAL` / `RISK-OFF` 구분
- 아웃오브샘플 검증을 통과한 모델만 적용하는 백테스트 기반 모델 관리

## 빠른 시작

### 요구 사항

- Python 3.10 이상 권장
- 인터넷 연결(시세 및 ETF 편입 종목 조회)

### 설치 및 실행

```powershell
git clone <저장소-URL>
cd institutional-flow-engine-python

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

브라우저에서 <http://127.0.0.1:8055>로 접속합니다.

Windows에서는 `run_dashboard.bat`을 더블 클릭해 의존성 설치와 실행을 한 번에 진행할 수도 있습니다.

## 테스트

네트워크 호출 없이 대시보드 레이아웃과 핵심 계산 로직을 점검합니다.

```powershell
python smoke_test.py
```

성공하면 다음 메시지가 출력됩니다.

```text
Smoke test passed: dashboard layout and datasets are available.
```

## 백테스트 및 모델 갱신

기본 설정으로 최근 5년 데이터를 사용해 모델 후보를 학습하고 검증하려면 다음 명령을 실행합니다.

```powershell
python backtest.py --years 5 --rebalance 5 --horizon 20 --train-fraction 0.65 --top-k 3 --cost-bps 10
```

주요 옵션은 다음과 같습니다.

| 옵션 | 기본값 | 설명 |
| --- | ---: | --- |
| `--years` | 5 | 조회할 과거 데이터 기간(년) |
| `--rebalance` | 5 | 리밸런싱 간격(거래일) |
| `--horizon` | 20 | 선행 수익률 측정 구간(거래일) |
| `--train-fraction` | 0.65 | 전체 기간 중 학습 구간 비율 |
| `--top-k` | 3 | 평가 포트폴리오에 포함할 상위 섹터 수 |
| `--cost-bps` | 10 | 거래비용 가정(bps) |
| `--holdings-limit` | 30 | 섹터별 ETF 편입 종목 사용 한도 |
| `--grid-step` | 0.1 | 팩터 가중치 탐색 간격 |
| `--output` | `rotation_model.json` | 결과 파일 경로 |

실행 결과는 기본적으로 `rotation_model.json`을 덮어씁니다. 새 후보는 검증 구간에서 기존 모델보다 아래 네 기준을 모두 충족할 때만 활성 모델로 승격됩니다.

- 거래비용 차감 후 초과수익률이 낮지 않을 것
- 순정보비율(net information ratio)이 낮지 않을 것
- 정보계수(IC)가 낮지 않을 것
- 평균 단방향 회전율이 높지 않을 것

현재 저장된 모델은 기본 복합 가중치를 유지하고 있습니다.

| 팩터 | 가중치 |
| --- | ---: |
| 20일 초과수익률 횡단면 순위 | 35% |
| 60일 초과수익률 횡단면 순위 | 30% |
| 공식 ETF 편입 종목 시장 폭 | 20% |
| 벤치마크 ETF 상대 거래량 | 15% |

## 계산 방법

### 방향성 거래대금

```text
거래대금 = 수정주가 × 거래량
방향성 거래대금 = sign(일간 수익률) × 거래대금
```

이는 거래 활동에 가격 방향을 부여한 값이며 ETF 순유입액, 설정·환매, 발행주식 수 변화 또는 기관 거래의 증거가 아닙니다.

### 시장 폭

VanEck, Global X, iShares, First Trust가 공개한 ETF 편입 종목과 비중을 이용해 50일·200일 이동평균 상회 비율을 계산합니다. 상승-하락 정규화 값은 다음과 같습니다.

```text
(상승 종목 수 - 하락 종목 수) / (상승 종목 수 + 하락 종목 수)
```

### 위험 선호 국면

다음 신호의 20거래일 추세와 광범위 시장 참여도를 결합합니다.

- `QQQ/SPY`: 성장주 대 대형주
- `HYG/LQD`: 하이일드채 대 투자등급채
- `IWM/SPY`: 소형주 대 대형주
- `XLY/XLP`: 경기소비재 대 필수소비재
- `VIX/VIX3M`: 단기 대 중기 변동성 기간구조

사용 가능한 크로스에셋 신호가 종합점수의 80%, 시장 폭이 20%를 차지합니다. 점수가 65 이상이면 `RISK-ON`, 35 이하면 `RISK-OFF`, 그 사이는 `NEUTRAL`로 표시합니다.

## 데이터와 캐시

- 수정주가와 거래량: `yfinance`를 통한 Yahoo Finance 데이터
- ETF 편입 종목: VanEck, Global X, iShares, First Trust 공식 공개 자료
- 시장 데이터 캐시: 5분
- 공식 편입 종목 캐시: 18시간
- 공식 자료 갱신 실패 시 이전 캐시를 사용하며, 캐시도 없으면 명시된 대체 종목군을 사용
- 별도의 API 키나 `.env` 설정은 필요하지 않음

캐시 파일은 `.cache/`에 저장되며 Git에 포함되지 않습니다.

## 프로젝트 구조

```text
.
├── app.py                # Dash 애플리케이션과 화면 구성
├── market_data.py        # 시세 조회, 지표 계산, 스냅샷 캐시
├── etf_holdings.py       # 공식 ETF 편입 종목 수집 및 대체 데이터 처리
├── rotation_model.py     # 로테이션 점수 및 모델 로딩
├── backtest.py           # 학습/검증 분리 백테스트와 모델 승격 판단
├── rotation_model.json   # 현재 활성 모델, 후보, 검증 결과
├── smoke_test.py         # 오프라인 스모크 테스트
├── assets/style.css      # 대시보드 스타일
├── requirements.txt      # Python 의존성
└── run_dashboard.bat     # Windows 실행 스크립트
```

## 한계와 주의사항

- 현재 ETF 편입 종목으로 과거 시장 폭을 계산하므로 생존편향이 있습니다.
- Yahoo Finance 데이터는 연구·정보 제공 목적이며 체결 수준의 시뮬레이션에는 적합하지 않습니다.
- 검증 구간은 하나의 시장 국면만 반영하며 미래 성과를 보장하지 않습니다.
- 주간 관측값에서 20거래일 선행수익률 구간이 겹치므로 관측치가 통계적으로 독립적이지 않습니다.
- 실제 운용 성과가 아니라 섹터 ETF의 횡단면 초과수익률을 평가합니다.
- 본 프로젝트는 투자 자문이나 매매 권유를 제공하지 않습니다.

## 향후 개선 방향

- ETF 발행주식 수와 NAV 변화를 이용한 설정·환매 추정
- CFTC COT 포지셔닝 데이터 연동
- FINRA 공매도 거래량 및 FRED 하이일드 스프레드 추가
- 옵션·선물 포지셔닝 데이터 통합
- 단위 테스트와 CI 워크플로 확장
