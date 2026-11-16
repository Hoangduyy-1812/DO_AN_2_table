"""Causal four-posture FSM. Separate from SVM/fall-alert state machine."""

class PostureFSM:
    def __init__(self,low_m,high_m,bend_drop_m,bend_timeout_s):
        self.low=low_m;self.high=high_m;self.drop=bend_drop_m;self.timeout=bend_timeout_s
        self.reset()

    def reset(self):
        self.last_t=None;self.high_point=None;self.episode=None

    def update(self,t_s,z,reset=False):
        if reset or self.last_t is not None and (t_s-self.last_t<=0 or t_s-self.last_t>.35):
            self.reset()
        self.last_t=t_s
        if z>=self.high:
            self.high_point=(t_s,z);self.episode=None
            return 'STAND'
        if self.episode is None and self.high_point is not None:
            t0,z0=self.high_point
            if t_s-t0<=.35:
                self.episode=(t0,z0)
            self.high_point=None
        if z<self.low:
            return 'LYING'
        if self.episode is not None:
            t0,z0=self.episode
            if t_s-t0<=self.timeout and z0-z>=self.drop:
                return 'BEND'
            if t_s-t0>self.timeout:self.episode=None
        return 'SIT'


def old_posture(z):
    return 'STAND' if z>=1.0 else 'SIT_OR_BEND' if z>=.48 else 'LYING'


def height_posture(z,low,high):
    return 'STAND' if z>=high else 'SIT_OR_BEND' if z>=low else 'LYING'
