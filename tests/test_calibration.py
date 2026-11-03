from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from calibration_guard import CalibrationGuard,control_values


def record(values):
    return {str(i):{'type':'Float','value':value} for i,value in enumerate(values)}


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.g=CalibrationGuard()
        self.initial=record([1,2,3,4,0])
        self.g.inspect('a',self.initial,0)
        self.assertTrue(self.g.inspect('a',self.initial,2))

    def test_single_legitimate_zero_is_saved_after_debounce(self):
        live=record([0,2,3,4,0])
        self.assertFalse(self.g.inspect('a',live,3))
        self.assertTrue(self.g.inspect('a',live,5))
        self.assertFalse(self.g.paused)

    def test_staggered_batch_zero_cannot_pollute_baseline(self):
        self.g.inspect('a',record([0,2,3,4,0]),3)
        self.g.inspect('a',record([0,0,3,4,0]),3.4)
        self.assertFalse(self.g.inspect('a',record([0,0,0,4,0]),3.8))
        self.assertTrue(self.g.paused)
        self.assertFalse(self.g.inspect('a',record([0,0,0,0,0]),100))
        self.assertEqual(self.g.baseline,self.initial)

    def test_anomaly_recovers_only_when_affected_values_return_and_stabilize(self):
        self.g.inspect('a',record([0,0,0,0,0]),3)
        self.assertFalse(self.g.inspect('a',self.initial,4))
        self.assertTrue(self.g.inspect('a',self.initial,7))
        self.assertTrue(self.g.resumed)

    def test_explicit_vr_initialization_waits_then_requests_restore(self):
        self.assertFalse(self.g.inspect('a',record([0]*5),3,{'TrackingType':1,'VRMode':1}))
        self.assertFalse(self.g.inspect('a',record([0]*5),20,{'TrackingType':6,'VRMode':1}))
        self.assertTrue(self.g.inspect('a',record([0]*5),23))
        self.assertTrue(self.g.resumed)

    def test_desktop_generic_rig_is_not_misidentified_as_calibration(self):
        self.assertTrue(self.g.inspect('a',self.initial,3,{'TrackingType':1,'VRMode':0}))
        self.assertFalse(self.g.paused)

    def test_missing_control_does_not_falsely_end_known_calibration(self):
        self.g.inspect('a',self.initial,3,{'TrackingType':0})
        self.assertFalse(self.g.inspect('a',self.initial,20,{}))
        self.assertTrue(self.g.paused)

    def test_avatar_change_discards_previous_avatars_baseline(self):
        self.assertFalse(self.g.inspect('b',record([0]*5),3))
        self.assertTrue(self.g.inspect('b',record([0]*5),5))
        self.assertFalse(self.g.paused)

    def test_own_restore_zero_is_not_treated_as_anomaly(self):
        zero=record([0]*5)
        self.g.inspect('a',zero,3,detect_zero=False)
        self.assertTrue(self.g.inspect('a',zero,5,detect_zero=False))
        self.assertFalse(self.g.paused)

    def test_controls_require_readable_and_correct_types(self):
        nodes={'/avatar/parameters/TrackingType':{'TYPE':'i','ACCESS':1,'VALUE':[0]},
               '/avatar/parameters/VRMode':{'TYPE':'f','ACCESS':1,'VALUE':[1.]},
               '/avatar/parameters/IsAnimatorEnabled':{'TYPE':'F','ACCESS':2,'VALUE':[False]}}
        self.assertEqual(control_values(nodes),{'TrackingType':0})


if __name__=='__main__':unittest.main()
