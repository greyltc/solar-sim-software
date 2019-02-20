import numpy
import time
from collections import deque

class mppt:
  """
  Maximum power point tracker class
  """
  dwell_time = 10  # number of seconds to spend in the soak phase of a mppt algorithm
  Voc = None
  Isc = None
  Vmpp = None  # voltage at max power point
  Impp = None  # current at max power point
  
  currentCompliance = None
  t0 = None  # the time we started the mppt algorithm
  
  def __init__(self, sm):
    self.sm = sm
    
  def reset(self):
    Voc = None
    Isc = None
    Vmpp = None  # voltage at max power point
    Impp = None  # current at max power point
    
    current_compliance = None
    t0 = None  # the time we started the mppt algorithm
    
  def which_max_power(self, vector):
    """
    given a list of raw measurements, figure out which one produced the highest power
    """
    v = numpy.array([e[0] for e in vector])
    i = numpy.array([e[1] for e in vector])  
    p = v*i*-1
    maxIndex = numpy.argmax(p)
    Vmpp = v[maxIndex]
    Pmax = p[maxIndex]
    Impp = i[maxIndex]
    # returns maximum power[W], Vmpp, Impp and the index
    return (Pmax, Vmpp, Impp, maxIndex)
    
  def launch_tracker(self, duration=30, callback = None, NPLC=-1):
    """
    general function to call begin a max power point tracking algorithm
    duration given in seconds, optionally calling callback function on each measurement point
    """
    if (self.Voc == None):
      print("WARNING: Not doing power point tracking. Voc not known.")
      return []
    self.t0 = time.time()  # start the mppt timer

    if self.Vmpp == None:
      self.Vmpp = 0.7 * self.Voc # start at 70% of Voc if nobody told us otherwise
      
    if self.current_compliance == None:
      current_compliance = 0.04  # assume 40mA compliance if nobody told us otherwise
    else:
      current_compliance = self.current_compliance
      
    if NPLC != -1:
      self.sm.setNPLC(NPLC)
    
    # do initial mppt dwell before we start the actual algorithm
    print("Teleporting to Mpp!")
    self.sm.setupDC(sourceVoltage=True, compliance=current_compliance, setPoint=self.Vmpp, senseRange='a')
    self.sm.write(':arm:source immediate') # this sets up the trigger/reading method we'll use below
    if duration <= 10:
      # if the user only wants to mppt for 20 or less seconds, shorten the initial dwell
      initial_soak = duration * 0.2
    else:
      initial_soak = 10
    print("Soaking @ Mpp (V={:0.2f}[mV]) for {:0.1f} seconds...".format(self.Vmpp*1000, initial_soak))
    q = self.sm.measureUntil(t_dwell=initial_soak)
    self.Impp = q[-1][1]  # use most recent current measurement as Impp
    if self.current_compliance == None:
      self.current_compliance = abs(self.Impp * 2)
    if self.Isc == None:
      # if nobody told us otherwise, assume Isc is 10% higher than Impp
      self.Isc = self.Impp * 1.1
  
    # run the a tracking algorithm
    pptv = self.really_dumb_tracker(duration, callback)
    
    run_time = time.time() - self.t0
    print('Final value seen by the max power point tracker after running for {:.1f} seconds is'.format(run_time))
    print('{:0.4f} mW @ {:0.2f} mV and {:0.2f} mA'.format(self.Vmpp*self.Impp*1000*-1, self.Vmpp*1000, self.Impp*1000))
    
    q.extend(pptv)
    
    return q
    
  def really_dumb_tracker(self, duration, callback = None):
    """
    A super dumb maximum power point tracking algorithm that
    alternates between periods of exploration around the mppt and periods of constant voltage dwells
    runs for duration seconds and returns a nx4 deque of the measurements it made
    """
    print("===Starting up dumb maximum power point tracking algorithm===")

    # work in voltage steps that are this fraction of Voc
    dV = self.Voc / 301

    # set exploration limits, this is probably an important variable
    dAngleMax = 7 #[exploration degrees] (plus and minus)
    
    q = deque()
    
    Impp = self.Impp
    Vmpp = self.Vmpp
    Voc = self.Voc
    Isc = self.Isc
    
    run_time = time.time() - self.t0
    while (run_time < duration):
      print("Exploring for new Mpp...")
      i_explore = numpy.array(Impp)
      v_explore = numpy.array(Vmpp)

      angleMpp = numpy.rad2deg(numpy.arctan(Impp/Vmpp*Voc/Isc))
      print('MPP ANGLE = {:0.2f}'.format(angleMpp))
      v_set = Vmpp
      highEdgeTouched = False
      lowEdgeTouched = False
      while (not(highEdgeTouched and lowEdgeTouched)):
        self.sm.setOutput(v_set)
        measurement = self.sm.measure()
        [v, i, tx, status] = measurement
        q.append(measurement)

        i_explore = numpy.append(i_explore, i)
        v_explore = numpy.append(v_explore, v)
        thisAngle = numpy.rad2deg(numpy.arctan(i/v*Voc/Isc))
        dAngle = angleMpp - thisAngle
        # print("dAngle={:}, highEdgeTouched={:}, lowEdgeTouched={:}".format(dAngle, highEdgeTouched, lowEdgeTouched))
        
        if dAngle > dAngleMax:
          highEdgeTouched = True
          dV = dV * -1
          print("Reached high voltage edge because angle exceeded")
        
        if dAngle < -dAngleMax:
          lowEdgeTouched = True
          dV = dV * -1
          print("Reached low voltage edge because angle exceeded")
          
        
        v_set = v_set + dV
        if ((v_set > 0) and (dV > 0)) or ((v_set < 0) and (dV < 0)):  #  walking towards Voc
          if (dV > 0) and v_set >= Voc:
            highEdgeTouched = True
            dV = dV * -1 # switch our voltage walking direction
            v_set = v_set + dV
            print("WARNING: Reached high voltage edge because we hit Voc")
            
          if (dV < 0) and v_set <= Voc:
            lowEdgeTouched = True
            dV = dV * -1 # switch our voltage walking direction
            v_set = v_set + dV
            print("WARNING: Reached high voltage edge because we hit Voc")
            
          
        else: #  walking towards Jsc
          if (dV > 0) and v_set >= 0:
            highEdgeTouched = True
            dV = dV * -1 # switch our voltage walking direction
            v_set = v_set + dV
            print("WARNING: Reached low voltage edge because we hit 0V")
            
          if (dV < 0) and v_set <= 0:
            lowEdgeTouched = True
            dV = dV * -1 # switch our voltage walking direction
            v_set = v_set + dV
            print("WARNING: Reached low voltage edge because we hit 0V")
        

      print("Done exploring.")

      # find the powers for the values we just explored
      p_explore = v_explore * i_explore * -1
      maxIndex = numpy.argmax(p_explore)
      Vmpp = v_explore[maxIndex]
      Impp = i_explore[maxIndex]

      print("New Mpp found: {:.6f} mW @ {:.6f} V".format(p_explore[maxIndex]*1000, Vmpp))

      dFromLastMppAngle = angleMpp - numpy.rad2deg(numpy.arctan(Impp/Vmpp*Voc/Isc))

      print("That's {:.6f} degrees different from the previous Mpp.".format(dFromLastMppAngle))
      
      run_time = time.time() - self.t0
      time_left = duration - run_time
      
      if time_left <= 0:
        break
      
      print("Teleporting to Mpp!")
      self.sm.setOutput(Vmpp)
      
      if time_left < self.dwell_time:
        dwell = time_left
      else:
        dwell = self.dwell_time
        
      print("Dwelling @ Mpp (V={:0.2f}[mV]) for {:0.1f} seconds...".format(Vmpp*1000, dwell))
      if callback != None:
        dq = self.sm.measureUntil(t_dwell=dwell, cb=callback)
      else:
        dq = self.sm.measureUntil(t_dwell=dwell)
      Impp = dq[-1][1]
      q.extend(dq)

      run_time = time.time() - self.t0
    
    self.Impp = Impp
    self.Vmpp = Vmpp
    return q