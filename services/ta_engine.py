import pandas as pd
import numpy as np


class TAEngine:

    def __init__(self, config=None):
        cfg = config or {}
        self.rsi_period = cfg.get('rsi_period', 14)
        self.rsi_overbought = cfg.get('rsi_overbought', 70)
        self.rsi_oversold = cfg.get('rsi_oversold', 30)
        self.macd_fast = cfg.get('macd_fast', 12)
        self.macd_slow = cfg.get('macd_slow', 26)
        self.macd_signal = cfg.get('macd_signal', 9)
        self.ema_period = cfg.get('ema_period', 20)
        self.bb_period = cfg.get('bb_period', 20)
        self.bb_std = cfg.get('bb_std', 2)

    def analyze(self, df):
        if df is None or len(df) < self.macd_slow + 10:
            return self._empty()

        close = df['close'].astype(float)

        rsi_s = self._rsi(close, self.rsi_period)
        macd_s, sig_s, hist_s = self._macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
        ema_s = close.ewm(span=self.ema_period, adjust=False).mean()
        bb_upper_s, bb_lower_s = self._bbands(close, self.bb_period, self.bb_std)

        def safe(s, default=0.0):
            v = s.iloc[-1]
            return float(v) if not pd.isna(v) else default

        r = safe(rsi_s, 50.0)
        m = safe(macd_s)
        ms = safe(sig_s)
        mh = safe(hist_s)
        mhp = float(hist_s.iloc[-2]) if len(hist_s) > 1 and not pd.isna(hist_s.iloc[-2]) else 0.0
        e = safe(ema_s)
        bu = safe(bb_upper_s)
        bl = safe(bb_lower_s)
        p = float(close.iloc[-1])
        bw = round(((bu - bl) / p) * 100, 2) if p else 0.0

        signal, confidence = self._signal(r, m, ms, mh, p, e, bu, bl, mhp)

        return {
            'signal': signal,
            'confidence': confidence,
            'price': round(p, 6),
            'indicators': {
                'rsi': round(r, 2),
                'macd': round(m, 4),
                'macd_signal': round(ms, 4),
                'macd_hist': round(mh, 4),
                'ema': round(e, 4),
                'bb_upper': round(bu, 4),
                'bb_lower': round(bl, 4),
                'bb_width': bw,
            }
        }

    def _rsi(self, close, period):
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _macd(self, close, fast, slow, signal):
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        sig = macd.ewm(span=signal, adjust=False).mean()
        hist = macd - sig
        return macd, sig, hist

    def _bbands(self, close, period, std):
        mid = close.rolling(period).mean()
        sigma = close.rolling(period).std()
        return mid + std * sigma, mid - std * sigma

    def _signal(self, rsi, macd, macd_sig, macd_hist, price, ema, bb_upper, bb_lower, prev_hist):
        score = 0
        reasons = 0

        if rsi < self.rsi_oversold:
            score += 2
            reasons += 1
        elif rsi < 45:
            score += 1
            reasons += 1
        elif rsi > self.rsi_overbought:
            score -= 2
            reasons += 1
        elif rsi > 55:
            score -= 1
            reasons += 1

        if macd_hist > 0 and prev_hist <= 0:
            score += 2
            reasons += 1
        elif macd_hist < 0 and prev_hist >= 0:
            score -= 2
            reasons += 1
        elif macd_hist > 0:
            score += 1
            reasons += 1
        elif macd_hist < 0:
            score -= 1
            reasons += 1

        if price > ema * 1.002:
            score += 1
            reasons += 1
        elif price < ema * 0.998:
            score -= 1
            reasons += 1

        if bb_lower and price <= bb_lower:
            score += 1
            reasons += 1
        elif bb_upper and price >= bb_upper:
            score -= 1
            reasons += 1

        max_score = reasons * 2 if reasons else 1
        confidence = min(int((abs(score) / max_score) * 100), 99)

        if score >= 2:
            return 'BUY', max(confidence, 55)
        elif score <= -2:
            return 'SELL', max(confidence, 55)
        else:
            return 'HOLD', max(confidence, 40)

    def _empty(self):
        return {
            'signal': 'HOLD',
            'confidence': 0,
            'price': 0.0,
            'indicators': {
                'rsi': 50.0,
                'macd': 0.0,
                'macd_signal': 0.0,
                'macd_hist': 0.0,
                'ema': 0.0,
                'bb_upper': 0.0,
                'bb_lower': 0.0,
                'bb_width': 0.0
            }
        }
