import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.phase2_validation import mean_ci, trade_stats, partition, epoch


class StatisticsTests(unittest.TestCase):
    def test_few_clusters_do_not_produce_inference(self):
        self.assertIsNone(mean_ci([(1,1),(2,-1)])['weekly_95_ci'])

    def test_cluster_bootstrap_and_no_variation(self):
        result=mean_ci([(i*604800,2) for i in range(10)])
        self.assertEqual(result['weekly_95_ci'],[2,2])

    def test_unknowns_not_wins_and_drawdown_chronological(self):
        rows=[{'at':3,'normal':{'r':2,'status':'TP'}},
              {'at':1,'normal':{'r':-1,'status':'SL'}},
              {'at':2,'normal':{'r':-1,'status':'SL'}},
              {'at':4,'normal':{'r':None,'status':'INCOMPLETE'}}]
        result=trade_stats(rows,'normal')
        self.assertEqual(result['realized_drawdown_r'],2)
        self.assertEqual(result['longest_losing_streak'],2)
        self.assertEqual(result['unknown'],1)
        self.assertAlmostEqual(result['win_rate'],1/3)

    def test_chronological_boundaries(self):
        self.assertEqual(partition(epoch('2025-09-30')),'train')
        self.assertEqual(partition(epoch('2025-10-01')),'validation')
        self.assertEqual(partition(epoch('2026-04-01')),'test')


if __name__=='__main__': unittest.main()
