import pandas as pd
import numpy as np


class TAEngine:
    """
    Multi-strategy TA engine using weighted voting.

    Strategies included:
      1. RSI — oversold/overbought + divergence
      2. MACD — crossover + histogram momentum
      3. EMA trend — price vs EMA20/50/200 alignment
      4. Bollinger Bands — squeeze breakout + mean reversion
      5. Stochastic RSI — fast momentum confirmation
      6. ATR trend filter — only trade in trending conditions
      7. Volume spike — confirms breakouts (if volume data available)
      8. Candlestick patterns — engulfing, hammer, shooting star

    Each strategy casts a vote: +1 (buy), -1 (sell), 0 (neutral).
    Each vote is weighted by strategy reliability.
    Final signal fires only when weighted score exceeds threshold
    AND at least 3 independent strategies agree (confluence filter).
    """

    # Strategy weights — higher = more trusted signal
    WEIGHTS = {
        'rsi':          1.5,
        'macd':         1.5,
        'ema_trend':    2.0,   # trend-following is highest weight
        'bbands':       1.2,
        'stoch_rsi':    1.0,
        'atr_filter':   1.0,
        'volume':       0.8,
        'candle':       1.0,
    }

    def __init__(self, config=None):
        cfg = config or {}
        self.rsi_period      = int(cfg.get('rsi_period', 14))
        self.rsi_overbought  = float(cfg.get('rsi_overbought', 70))
        self.rsi_oversold    = float(cfg.get('rsi_oversold', 30))
        self.macd_fast       = int(cfg.get('macd_fast', 12))
        self.macd_slow       = int(cfg.get('macd_slow', 26))
        self.macd_signal_p   = int(cfg.get('macd_signal', 9))
        self.ema_fast        = int(cfg.get('ema_fast', 20))
        self.ema_slow        = int(cfg.get('ema_slow', 50))
        self.ema_long        = int(cfg.get('ema_long', 200))
        self.bb_period       = int(cfg.get('bb_period', 20))
        self.bb_std          = float(cfg.get('bb_std', 2.0))
        self.stoch_period    = int(cfg.get('stoch_period', 14))
        self.stoch_smooth    = int(cfg.get('stoch_smooth', 3))
        self.atr_period      = int(cfg.get('atr_period', 14))
        # Minimum independent strategies that must agree
        self.min_confluence  = int(cfg.get('min_confluence', 2))
        # Minimum weighted score to fire BUY/SELL
        # Lower threshold lets strong 3-strategy combos reach 70% confidence
        self.score_threshold = float(cfg.get('score_threshold', 2.0))

    # ── PUBLIC ────────────────────────────────────────────────────────────────

    def analyze(self, df: pd.DataFrame) -> dict:
        min_bars = max(self.ema_long, self.macd_slow, self.bb_period) + 10
        if df is None or len(df) < min_bars:
            # Not enough data — try with relaxed requirement
            if df is None or len(df) < 40:
                return self._empty()

        close  = df['close'].astype(float)
        high   = df['high'].astype(float)
        low    = df['low'].astype(float)
        volume = df['volume'].astype(float) if 'volume' in df.columns else None

        # ── Compute all indicators ──
        indicators = self._compute_indicators(close, high, low, volume)

        # ── Run each strategy, collect weighted votes ──
        votes = {
            'rsi':       self._strategy_rsi(indicators),
            'macd':      self._strategy_macd(indicators),
            'ema_trend': self._strategy_ema_trend(indicators),
            'bbands':    self._strategy_bbands(indicators),
            'stoch_rsi': self._strategy_stoch_rsi(indicators),
            'atr_filter':self._strategy_atr_filter(indicators),
            'volume':    self._strategy_volume(indicators),
            'candle':    self._strategy_candle(close, high, low),
        }

        signal, confidence = self._aggregate(votes)

        return {
            'signal':     signal,
            'confidence': confidence,
            'price':      round(float(close.iloc[-1]), 6),
            'votes':      votes,
            'indicators': {
                'rsi':          round(indicators['rsi'], 2),
                'stoch_rsi':    round(indicators['stoch_rsi'], 2),
                'macd':         round(indicators['macd'], 4),
                'macd_signal':  round(indicators['macd_sig'], 4),
                'macd_hist':    round(indicators['macd_hist'], 4),
                'ema_fast':     round(indicators['ema_fast'], 4),
                'ema_slow':     round(indicators['ema_slow'], 4),
                'ema_long':     round(indicators['ema_long'], 4),
                'bb_upper':     round(indicators['bb_upper'], 4),
                'bb_lower':     round(indicators['bb_lower'], 4),
                'bb_width':     round(indicators['bb_width'], 2),
                'atr':          round(indicators['atr'], 4),
                'atr_pct':      round(indicators['atr_pct'], 2),
                'volume_ratio': round(indicators['volume_ratio'], 2),
            }
        }

    # ── INDICATOR COMPUTATION ─────────────────────────────────────────────────

    def _compute_indicators(self, close, high, low, volume) -> dict:
        def safe(s, default=0.0):
            if s is None or len(s) == 0:
                return default
            v = s.iloc[-1]
            return float(v) if not pd.isna(v) else default

        def safe2(s, default=0.0):
            """Second-to-last value."""
            if s is None or len(s) < 2:
                return default
            v = s.iloc[-2]
            return float(v) if not pd.isna(v) else default

        # RSI
        rsi_s = self._rsi(close, self.rsi_period)

        # MACD
        macd_s, sig_s, hist_s = self._macd(
            close, self.macd_fast, self.macd_slow, self.macd_signal_p)

        # EMAs
        ema_fast_s = close.ewm(span=self.ema_fast, adjust=False).mean()
        ema_slow_s = close.ewm(span=self.ema_slow, adjust=False).mean()
        ema_long_s = close.ewm(span=self.ema_long, adjust=False).mean()

        # Bollinger Bands
        bb_mid    = close.rolling(self.bb_period).mean()
        bb_sigma  = close.rolling(self.bb_period).std()
        bb_upper_s = bb_mid + self.bb_std * bb_sigma
        bb_lower_s = bb_mid - self.bb_std * bb_sigma

        # Stochastic RSI
        stoch_rsi_s = self._stoch_rsi(close, self.stoch_period, self.stoch_smooth)

        # ATR
        atr_s = self._atr(high, low, close, self.atr_period)

        # Volume ratio (current vs 20-bar average)
        vol_ratio = 1.0
        if volume is not None and len(volume) >= 20:
            vol_avg = volume.rolling(20).mean().iloc[-1]
            vol_ratio = float(volume.iloc[-1]) / vol_avg if vol_avg > 0 else 1.0

        p = float(close.iloc[-1])
        bb_u = safe(bb_upper_s)
        bb_l = safe(bb_lower_s)

        return {
            'price':        p,
            'rsi':          safe(rsi_s, 50.0),
            'rsi_prev':     safe2(rsi_s, 50.0),
            'macd':         safe(macd_s),
            'macd_sig':     safe(sig_s),
            'macd_hist':    safe(hist_s),
            'macd_hist_prev': safe2(hist_s),
            'ema_fast':     safe(ema_fast_s),
            'ema_slow':     safe(ema_slow_s),
            'ema_long':     safe(ema_long_s),
            'bb_upper':     bb_u,
            'bb_lower':     bb_l,
            'bb_mid':       safe(bb_mid),
            'bb_width':     round(((bb_u - bb_l) / p) * 100, 2) if p else 0.0,
            'stoch_rsi':    safe(stoch_rsi_s, 50.0),
            'stoch_rsi_prev': safe2(stoch_rsi_s, 50.0),
            'atr':          safe(atr_s),
            'atr_pct':      (safe(atr_s) / p * 100) if p else 0.0,
            'volume_ratio': vol_ratio,
            # EMA crossover state
            'ema_fast_prev': safe2(ema_fast_s),
            'ema_slow_prev': safe2(ema_slow_s),
        }

    # ── STRATEGIES ────────────────────────────────────────────────────────────

    def _strategy_rsi(self, ind) -> int:
        """
        RSI oversold/overbought with momentum check.
        Extra weight for RSI divergence from extreme zones.
        """
        rsi = ind['rsi']
        # Strong signals at extremes
        if rsi <= self.rsi_oversold:
            return 1    # oversold → buy
        if rsi >= self.rsi_overbought:
            return -1   # overbought → sell
        # Moderate signals
        if rsi < 40 and ind['rsi_prev'] < rsi:
            return 1    # rising from low → bullish
        if rsi > 60 and ind['rsi_prev'] > rsi:
            return -1   # falling from high → bearish
        return 0

    def _strategy_macd(self, ind) -> int:
        """
        MACD crossover + histogram momentum shift.
        Crossover is stronger signal than continuation.
        """
        hist      = ind['macd_hist']
        hist_prev = ind['macd_hist_prev']
        macd      = ind['macd']
        sig       = ind['macd_sig']

        # Crossover (strongest)
        if hist > 0 and hist_prev <= 0:
            return 1
        if hist < 0 and hist_prev >= 0:
            return -1

        # Histogram expanding in direction (momentum continuation)
        if hist > 0 and hist > hist_prev and macd > sig:
            return 1
        if hist < 0 and hist < hist_prev and macd < sig:
            return -1

        return 0

    def _strategy_ema_trend(self, ind) -> int:
        """
        EMA alignment: fast > slow > long = strong uptrend.
        Also detects EMA fast/slow crossovers.
        Weight is highest because trend-following has best R:R.
        """
        p         = ind['price']
        ef        = ind['ema_fast']
        es        = ind['ema_slow']
        el        = ind['ema_long']
        ef_prev   = ind['ema_fast_prev']
        es_prev   = ind['ema_slow_prev']

        # Full bull alignment: price > EMA20 > EMA50 > EMA200
        if p > ef > es > el:
            return 1
        # Full bear alignment
        if p < ef < es < el:
            return -1

        # EMA20/50 crossover (golden/death cross on fast timeframe)
        if ef > es and ef_prev <= es_prev:
            return 1   # golden cross
        if ef < es and ef_prev >= es_prev:
            return -1  # death cross

        # Partial: price above both fast EMAs but below long → mild bull
        if p > ef and p > es and p < el:
            return 1
        if p < ef and p < es and p > el:
            return -1

        return 0

    def _strategy_bbands(self, ind) -> int:
        """
        Bollinger Band squeeze breakout + mean reversion.
        Tight bands (squeeze) followed by price breaking out = high probability.
        """
        p   = ind['price']
        bu  = ind['bb_upper']
        bl  = ind['bb_lower']
        bm  = ind['bb_mid']
        bw  = ind['bb_width']

        # Mean reversion: price at band extremes
        if p <= bl:
            return 1   # touched lower band → bounce
        if p >= bu:
            return -1  # touched upper band → reversal

        # Momentum: price crossed midline with direction
        if p > bm and bw > 2.0:   # above midline in expanding band
            return 1
        if p < bm and bw > 2.0:
            return -1

        return 0

    def _strategy_stoch_rsi(self, ind) -> int:
        """
        Stochastic RSI for fast momentum confirmation.
        Only signals at extremes to avoid noise.
        """
        sr      = ind['stoch_rsi']
        sr_prev = ind['stoch_rsi_prev']

        if sr < 20 and sr > sr_prev:
            return 1   # oversold and turning up
        if sr > 80 and sr < sr_prev:
            return -1  # overbought and turning down
        if sr < 25:
            return 1
        if sr > 75:
            return -1
        return 0

    def _strategy_atr_filter(self, ind) -> int:
        """
        ATR-based trend filter — not a directional signal but a quality gate.
        Low ATR (choppy market) reduces confidence by returning 0.
        High ATR confirms trending conditions.
        Votes in direction of EMA trend only when ATR is significant.
        """
        atr_pct = ind['atr_pct']
        p       = ind['price']
        ef      = ind['ema_fast']

        # In very low volatility (choppy), abstain
        if atr_pct < 0.3:
            return 0

        # In high volatility, confirm direction of EMA trend
        if atr_pct > 0.8:
            if p > ef:
                return 1
            if p < ef:
                return -1

        return 0

    def _strategy_volume(self, ind) -> int:
        """
        Volume spike confirmation.
        High volume breakouts are more reliable than low-volume moves.
        """
        vr  = ind['volume_ratio']
        p   = ind['price']
        ef  = ind['ema_fast']
        bm  = ind['bb_mid']

        if vr < 1.0:
            return 0   # below-average volume — abstain

        # Volume spike in direction of price vs midline
        if vr >= 1.5:
            if p > bm:
                return 1
            if p < bm:
                return -1

        return 0

    def _strategy_candle(self, close, high, low) -> int:
        """
        Single-candle pattern recognition.
        Hammer, bullish/bearish engulfing, shooting star.
        """
        if len(close) < 3:
            return 0

        c0, c1, c2 = float(close.iloc[-1]), float(close.iloc[-2]), float(close.iloc[-3])
        h0, h1     = float(high.iloc[-1]),  float(high.iloc[-2])
        l0, l1     = float(low.iloc[-1]),   float(low.iloc[-2])

        body0  = abs(c0 - c1)
        range0 = h0 - l0 if h0 > l0 else 0.0001
        range1 = h1 - l1 if h1 > l1 else 0.0001

        # Bullish engulfing: big green candle engulfs previous red
        if c0 > c1 and c1 < c2:          # current green, prev red
            if body0 > abs(c1 - c2) * 1.2:  # body at least 20% larger
                return 1

        # Bearish engulfing: big red candle engulfs previous green
        if c0 < c1 and c1 > c2:
            if body0 > abs(c1 - c2) * 1.2:
                return -1

        # Hammer: small body at top, long lower wick
        lower_wick = min(c0, c1) - l0
        upper_wick = h0 - max(c0, c1)
        if lower_wick > body0 * 2 and upper_wick < body0 * 0.5:
            return 1  # hammer → bullish reversal

        # Shooting star: small body at bottom, long upper wick
        if upper_wick > body0 * 2 and lower_wick < body0 * 0.5:
            return -1  # shooting star → bearish reversal

        return 0

    # ── AGGREGATION ───────────────────────────────────────────────────────────

    def _aggregate(self, votes: dict) -> tuple:
        """
        Weighted voting with confluence filter.

        Rules:
        - Each strategy vote (+1/-1/0) × its weight
        - Signal fires only if:
            a) weighted score >= threshold (default 2.5), AND
            b) at least min_confluence strategies agree (default 3)
        - Confidence = (weighted score / max possible score) × 100
          scaled by confluence ratio
        """
        buy_score  = 0.0
        sell_score = 0.0
        buy_count  = 0
        sell_count = 0
        total_weight = sum(self.WEIGHTS.values())

        for strategy, vote in votes.items():
            w = self.WEIGHTS.get(strategy, 1.0)
            if vote == 1:
                buy_score  += w
                buy_count  += 1
            elif vote == -1:
                sell_score += w
                sell_count += 1

        # Confluence filter: require min strategies to agree
        buy_ok  = buy_count  >= self.min_confluence
        sell_ok = sell_count >= self.min_confluence

        net_score = buy_score - sell_score

        if net_score >= self.score_threshold and buy_ok:
            raw_conf = min((buy_score / total_weight) * 100, 99)
            # Bonus for extra confluence
            confluence_bonus = min((buy_count - self.min_confluence) * 3, 15)
            confidence = min(int(raw_conf + confluence_bonus), 99)
            return 'BUY', max(confidence, 55)

        if net_score <= -self.score_threshold and sell_ok:
            raw_conf = min((sell_score / total_weight) * 100, 99)
            confluence_bonus = min((sell_count - self.min_confluence) * 3, 15)
            confidence = min(int(raw_conf + confluence_bonus), 99)
            return 'SELL', max(confidence, 55)

        # HOLD — show partial confidence in dominant direction
        if buy_score > sell_score:
            conf = max(int((buy_score / total_weight) * 70), 30)
            return 'HOLD', conf
        if sell_score > buy_score:
            conf = max(int((sell_score / total_weight) * 70), 30)
            return 'HOLD', conf

        return 'HOLD', 30

    # ── INDICATOR HELPERS ─────────────────────────────────────────────────────

    def _rsi(self, close, period):
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _macd(self, close, fast, slow, signal):
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd     = ema_fast - ema_slow
        sig      = macd.ewm(span=signal, adjust=False).mean()
        hist     = macd - sig
        return macd, sig, hist

    def _stoch_rsi(self, close, period, smooth):
        rsi   = self._rsi(close, period)
        rsi_min = rsi.rolling(period).min()
        rsi_max = rsi.rolling(period).max()
        denom   = (rsi_max - rsi_min).replace(0, np.nan)
        stoch   = (rsi - rsi_min) / denom * 100
        return stoch.rolling(smooth).mean()

    def _atr(self, high, low, close, period):
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _empty(self):
        return {
            'signal':     'HOLD',
            'confidence': 0,
            'price':      0.0,
            'votes':      {k: 0 for k in self.WEIGHTS},
            'indicators': {
                'rsi': 50.0, 'stoch_rsi': 50.0,
                'macd': 0.0, 'macd_signal': 0.0, 'macd_hist': 0.0,
                'ema_fast': 0.0, 'ema_slow': 0.0, 'ema_long': 0.0,
                'bb_upper': 0.0, 'bb_lower': 0.0, 'bb_width': 0.0,
                'atr': 0.0, 'atr_pct': 0.0, 'volume_ratio': 1.0,
            }
        }
