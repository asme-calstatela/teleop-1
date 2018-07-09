#!/usr/bin/env python

# Modified By: Jeovanny Reyes
# Modified On: 6/5/18

# Note: It takes about 1596 ticks for one complete revolution
# Inputs: Takes in std_msgs of Float32 from the topics "left_enc_ticks" and
#          "right_enc_ticks" contain encoder ticks information
#

# Cal State LA Robotics Laboratory

# DISCLAIMER.
     # New_Odom.py - follows the output of a wheel encoder and
    #  creates tf and odometry messages.
    #   some code borrowed from the arbotix diff_controller script
    #   A good reference: http://rossum.sourceforge.net/papers/DiffSteer/
    #
    #    Copyright (C) 2012 Jon Stephan.
    #
    #    This program is free software: you can redistribute it and/or modify
    #    it under the terms of the GNU General Public License as published by
    #    the Free Software Foundation, either version 3 of the License, or
    #    (at your option) any later version.
    #    This program is distributed in the hope that it will be useful,
    #    but WITHOUT ANY WARRANTY; without even the implied warranty of
    #    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    #    GNU General Public License for more details.
    #    You should have received a copy of the GNU General Public License
    #    along with this program.  If not, see <http://www.gnu.org/licenses/>.
    #
    #  ----------------------------------
    #  Portions of this code borrowed from the arbotix_python diff_controller.
    #
    # diff_controller.py - controller for a differential drive
    #  Copyright (c) 2010-2011 Vanadium Labs LLC.  All right reserved.
    #  Redistribution and use in source and binary forms, with or without
    #  modification, are permitted provided that the following conditions are met:
    #      * Redistributions of source code must retain the above copyright
    #        notice, this list of conditions and the following disclaimer.
    #      * Redistributions in binary form must reproduce the above copyright
    #        notice, this list of conditions and the following disclaimer in the
    #        documentation and/or other materials provided with the distribution.
    #      * Neither the name of Vanadium Labs LLC nor the names of its
    #        contributors may be used to endorse or promote products derived
    #        from this software without specific prior written permission.
    #
    #  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
    #  ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
    #  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
    #  DISCLAIMED. IN NO EVENT SHALL VANADIUM LABS BE LIABLE FOR ANY DIRECT, INDIRECT,
    #  INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
    #  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
    #  OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
    #  LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
    #  OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
    #  ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import rospy
from math import sin, cos, pi

from geometry_msgs.msg import Quaternion # To store the linear and angular velocity information
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from tf.broadcaster import TransformBroadcaster # To publish the tf information.
from std_msgs.msg import Float32 # The tick counts are stored in Float64 information from Arduino code.

class Odom_info(object):
    def __init__(self):
        rospy.init_node("Odom_info")
        self.nodename = rospy.get_name()
        rospy.loginfo("-I- %s started" % self.nodename)

        #### parameters #######
        self.rate = rospy.get_param('~rate',10.0)  # the rate at which to publish the transform in Hz
        self.ticks_meter = float(rospy.get_param('ticks_meter', 2080))  # The number of wheel encoder ticks per meter of travel
        self.base_width = float(rospy.get_param('~base_width', 0.5207)) # The wheel base width in meters. Distance from center of left wheel to right wheel.
        # Wheel distance: 20.5 inches

        self.base_frame_id = rospy.get_param('~base_frame_id','base_link') # the name of the base frame of the robot.
        self.odom_frame_id = rospy.get_param('~odom_frame_id', 'odom') # the name of the odometry reference frame. May need to create this!

        self.encoder_min = rospy.get_param('encoder_min', -40000) # Need to obtain this through experiment!
        self.encoder_max = rospy.get_param('encoder_max', 40000) # Need to obtain this through experiment!
        self.encoder_low_wrap = rospy.get_param('wheel_low_wrap', (self.encoder_max - self.encoder_min) * 0.3 + self.encoder_min )
        self.encoder_high_wrap = rospy.get_param('wheel_high_wrap', (self.encoder_max - self.encoder_min) * 0.7 + self.encoder_min )

        self.t_delta = rospy.Duration(1.0/self.rate)
        self.t_next = rospy.Time.now() + self.t_delta

        # internal data
        self.enc_left = None        # wheel encoder readings
        self.enc_right = None
        self.left = 0               # actual values coming back from robot
        self.right = 0
        self.lmult = 0
        self.rmult = 0
        self.prev_lencoder = 0
        self.prev_rencoder = 0
        self.x = 0                  # position in xy plane. Vertical Axis(x) Horizontal Axis (y). Right Hand Rule
        self.y = 0
        self.th = 0
        self.dx = 0                 # Speed of linear travel
        self.dr = 0                 # Speed of angular rotation
        self.then = rospy.Time.now()

        # subscriptions
        rospy.Subscriber("left_enc_ticks", Float32, self.lwheelCallback) # Can be found in Arduino Code.
        rospy.Subscriber("right_enc_ticks", Float32, self.rwheelCallback) # Can be found in Arduino Code.
        self.odomPub = rospy.Publisher("odom", Odometry, queue_size=100)
        self.left_lin_vel = rospy.Publisher("left_lin_vel", Float32, queue_size = 100) # Publishes the velocity of the left wheel
        self.right_lin_vel = rospy.Publisher("right_lin_vel", Float32, queue_size = 100) # Publishes the velocity of the right wheel
        self.lin_vel = rospy.Publisher("lin_vel", Float32, queue_size = 100) # Publishes the linear velocity in m/sec
        self.ang_vel = rospy.Publisher("ang_vel", Float32, queue_size = 100) # Publishes the angular velocity in m/sec
        self.odomBroadcaster = TransformBroadcaster()
        print("Made it past subscriptions")
        self.spin()

    def spin(self): # To keep things running.
        r = rospy.Rate(self.rate)
        while not rospy.is_shutdown():
            self.update()
            r.sleep()

    def update(self):
        now = rospy.Time.now()
        if now > self.t_next:
            elapsed = now - self.then
            self.then = now
            elapsed = elapsed.to_sec()

            # calculate odometry
            if self.enc_left == None: # Initializing and instantiating encoder counts.
                d_left = 0
                d_right = 0
            else:
                d_left = (self.left - self.enc_left) / self.ticks_meter # Current minus previous
                d_right = (self.right - self.enc_right) / self.ticks_meter # Current minues prvious
            rospy.loginfo(d_left)
            rospy.loginfo(d_right)
            self.enc_left = self.left # Current data gets assigned as old data for next iteration
            self.enc_right = self.right

            # distance traveled is the average of the two wheels
            d = ( d_left + d_right ) / 2
            # this approximation works (in radians) for small angles
            th = ( d_right - d_left ) / self.base_width # Calculates difference of the angles
            # calculate velocities
            # First calculate speed of each wheel independently:
            self.left_dx = d_left / elapsed
            self.right_dx = d_right / elapsed
            if (d_left == 0 and d_right == 0): # Wheels Not Moving
                self.dx = 0
                self.dr = 0
                print("Melo Not Moving!")
            elif ((d_left == 0 and d_right != 0) or (d_left < 0 and d_right > 0)): # Right Wheel moving only or Right going forward and left going backward
                self.dx = 0 # Linear Velocity (zero)
                self.dr = th / elapsed
                print("Rotating Left")
            elif ((d_left !=0 and d_right ==0) or (d_left > 0 and d_right < 0)): # Left Wheel Moving only or Left Wheel Moving forward and right going backward
                self.dx = 0
                self.dr = th / elapsed
                print("Rotating Right")
            elif (d_left > 0 and d_right >0): # Positive Distance
                self.dx = d / elapsed # Linear Velocity (+)
                self.dr = 0
                print("Melo Moving Forward")
            elif(d_left < 0 and d_right < 0): # Negative Distance
                self.dx = d / elapsed # Linear Velocity (-)
                self.dr = 0
                print("Melo Moving Backward")

            #self.dx = d / elapsed # Linear Velocity
            #self.dr = th / elapsed # Angular Velocity
            self.left_lin_vel.publish(self.left_dx) # Publishes the linear velocity of the left wheel in m/sec
            self.right_lin_vel.publish(self.right_dx) # Publishes the linear velocity of the right wheel in m/sec
            self.lin_vel.publish(self.dx) # Publishes linear velocity in m/sec
            self.ang_vel.publish(self.dr) # Publishes the angular velocity in m/sec


            if (d != 0):
                # calculate distance traveled in x and y
                x = cos( th ) * d
                y = -sin( th ) * d
                # calculate the final position of the robot
                self.x = self.x + ( cos( self.th ) * x - sin( self.th ) * y ) # Distance gets add on
                self.y = self.y + ( sin( self.th ) * x + cos( self.th ) * y ) # Distance gets add on
            if( th != 0):
                self.th = self.th + th

            # publish the odom information
            quaternion = Quaternion()
            quaternion.x = 0.0
            quaternion.y = 0.0
            quaternion.z = sin( self.th / 2 )
            quaternion.w = cos( self.th / 2 )
            self.odomBroadcaster.sendTransform(
                (self.x, self.y, 0),
                (quaternion.x, quaternion.y, quaternion.z, quaternion.w),
                rospy.Time.now(),
                self.base_frame_id,
                self.odom_frame_id
                )

            odom = Odometry()
            odom.header.stamp = now
            odom.header.frame_id = self.odom_frame_id
            odom.pose.pose.position.x = self.x
            odom.pose.pose.position.y = self.y
            odom.pose.pose.position.z = 0
            odom.pose.pose.orientation = quaternion
            odom.child_frame_id = self.base_frame_id
            odom.twist.twist.linear.x = self.dx
            odom.twist.twist.linear.y = 0
            odom.twist.twist.angular.z = self.dr
            self.odomPub.publish(odom)


    def lwheelCallback(self, msg): # Left wheel callback
        enc = msg.data
        if (enc < self.encoder_low_wrap and self.prev_lencoder > self.encoder_high_wrap):
            self.lmult = self.lmult + 1

        if (enc > self.encoder_high_wrap and self.prev_lencoder < self.encoder_low_wrap):
            self.lmult = self.lmult - 1

        self.left = 1.0 * (enc + self.lmult * (self.encoder_max - self.encoder_min))
        self.prev_lencoder = enc

    def rwheelCallback(self, msg): # Right wheel callback
        enc = msg.data
        if(enc < self.encoder_low_wrap and self.prev_rencoder > self.encoder_high_wrap):
            self.rmult = self.rmult + 1

        if(enc > self.encoder_high_wrap and self.prev_rencoder < self.encoder_low_wrap):
            self.rmult = self.rmult - 1

        self.right = 1.0 * (enc + self.rmult * (self.encoder_max - self.encoder_min))
        self.prev_rencoder = enc

#############################################################################
#############################################################################
if __name__ == '__main__':
    Odom_info()
    #""" main """
    #try:
    #    odominf = Odom_info()
    #    odominf.spin()
    #except rospy.ROSInterruptException:
#pass