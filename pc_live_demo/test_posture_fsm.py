import unittest
from posture_fsm import PostureFSM,old_posture,height_posture

CONFIG=dict(low_m=.3555,high_m=.9155,bend_drop_m=.241,bend_timeout_s=2.49)


class PostureTests(unittest.TestCase):
    def test_old_ui_is_reproduced(self):
        self.assertEqual(old_posture(1.0),'STAND')
        self.assertEqual(old_posture(.48),'SIT_OR_BEND')
        self.assertEqual(old_posture(.479),'LYING')

    def test_data_cutoffs_are_used(self):
        self.assertEqual(height_posture(.95,.3555,.9155),'STAND')
        self.assertEqual(old_posture(.95),'SIT_OR_BEND')
        self.assertEqual(height_posture(.4,.3555,.9155),'SIT_OR_BEND')

    def test_lowering_is_provisional_then_becomes_sitting(self):
        d=PostureFSM(**CONFIG)
        self.assertEqual(d.update(0,1.2),'STAND')
        self.assertEqual(d.update(.1,.7),'BEND')
        for i in range(2,28):last=d.update(i*.1,.7)
        self.assertEqual(last,'SIT')

    def test_gap_does_not_reuse_old_standing_history(self):
        d=PostureFSM(**CONFIG);d.update(0,1.2)
        self.assertEqual(d.update(1,.7),'SIT')

    def test_lying_overrides_bending_candidate(self):
        d=PostureFSM(**CONFIG);d.update(0,1.2)
        self.assertEqual(d.update(.1,.2),'LYING')

    def test_recovery_is_not_used_to_relabel_the_past(self):
        d=PostureFSM(**CONFIG)
        before=[d.update(0,1.2),d.update(.1,.7)]
        self.assertEqual(d.update(.2,1.2),'STAND')
        self.assertEqual(before,['STAND','BEND'])


if __name__=='__main__':unittest.main()
