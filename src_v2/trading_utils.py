import numpy as np
from env import leverage_large_edge, leverage_small_edge

class TradingPrice:
    def __init__(self):
        # Corrected list syntax
        self.prob = ['Flat', 'Large Down', 'Large Up', 'Medium Down', 'Medium Up']
        self.weights = np.array([0 ,  -2 , 2 , -1 , 1])

    def calculate_edge(self, probs):
        # Handle sklearn predict_proba output which is (1, n_classes)
        if hasattr(probs, 'ndim') and probs.ndim > 1:
            probs = probs.flatten()
        edge = np.dot(self.weights, probs)
        return edge

    def get_trade_decision(self, edge):
        """
        Returns (side, leverage, description)
        EV > +0.15      Big long
        +0.05 to +0.15  Small long
        -0.05 to +0.05  No trade
        -0.15 to -0.05  Small short
        < -0.15         Big short
        """
        if edge > 0.15:
            return "BUY", leverage_large_edge, "Big Long"
        elif 0.05 <= edge <= 0.15:
            return "BUY", leverage_small_edge, "Small Long"
        elif -0.05 < edge < 0.05:
            return "NEUTRAL", 0, "No Trade"
        elif -0.15 <= edge <= -0.05:
            return "SELL", leverage_small_edge, "Small Short"
        elif edge < -0.15:
            return "SELL", leverage_large_edge, "Big Short"
        
        return "NEUTRAL", 0, "No Trade"  # Fallback