import pickle as pkl 
from sklearn.ensemble import RandomForestClassifier
import pandas as pd
from data_ingestion import DataIngestion
class Classifier:
    def __init__(self) :
        with open('CryptoV2/src/best_random_forest_model.pkl' , 'rb') as file :
            self.model = pkl.load(file=file)
    def predict(self , df : pd.DataFrame):
        x = df.iloc[[-2]]
        probs = self.model.predict_proba(x)
        return probs 


if __name__ == '__main__' :
    model = Classifier()
    data_p = DataIngestion()
    data = data_p.get_data('BTCUSDT')
    f_data = data_p.__engineer_features__(data)
    prob = model.predict(f_data)
    print(prob)
