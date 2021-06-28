#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2015-2019, NewAE Technology Inc
# All rights reserved.
#
# Find this and more at newae.com - this file is part of the chipwhisperer
# project, http://www.chipwhisperer.com . ChipWhisperer is a registered
# trademark of NewAE Technology Inc in the US & Europe.
#
#    This file is part of chipwhisperer.
#
#    chipwhisperer is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    chipwhisperer is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with chipwhisperer.  If not, see <http://www.gnu.org/licenses/>.
#=================================================
import logging
import time
from datetime import datetime
import os.path
from ._base import TargetTemplate
from chipwhisperer.hardware.naeusb.naeusb import NAEUSB
from chipwhisperer.hardware.naeusb.pll_cdce906 import PLLCDCE906
from chipwhisperer.hardware.naeusb.fpga import FPGA
from chipwhisperer.common.utils import util
from chipwhisperer.common.utils.util import camel_case_deprecated


class CW305_USB(object):
    REQ_SYSCFG = 0x22
    REQ_VCCINT = 0x31
    SYSCFG_CLKOFF = 0x04
    SYSCFG_CLKON = 0x05
    SYSCFG_TOGGLE = 0x06
    VCCINT_XORKEY = 0xAE


class CW305(TargetTemplate):

    """CW305 target object.

    This class contains the public API for the CW305 hardware.
    To connect to the CW305, the easiest method is::

        import chipwhisperer as cw
        scope = cw.scope()
        target = cw.target(scope,
                targets.CW305, bsfile=<valid FPGA bitstream file>)

    Note that connecting to the CW305 includes programming the CW305 FPGA.
    For more help about CW305 settings, try help() on this CW305 submodule:

       * target.pll
    """


    _name = "ChipWhisperer CW305 (Artix-7)"

    def __init__(self):
        TargetTemplate.__init__(self)
        self._naeusb = NAEUSB()
        self.pll = PLLCDCE906(self._naeusb, ref_freq = 12.0E6)
        self.fpga = FPGA(self._naeusb)

        self.hw = None
        self.oa = None

        self._woffset = 0x400

        self._clksleeptime = 1
        self._clkusbautooff = True
        self.last_key = bytearray([0]*16)


    def fpga_write(self, addr, data):
        """Write to an address on the FPGA

        Args:
            addr (int): Address to write to
            data (list): Data to write to addr

        Raises:
            IOError: User attempted to write to a read-only location
        """
        if addr < self._woffset:
            raise IOError("Write to read-only location: 0x%04x"%addr)

        return self._naeusb.cmdWriteMem(addr, data)

    def fpga_read(self, addr, readlen):
        """Read from an address on the FPGA

        Args:
            addr (int): Address to read from
            readlen (int): Length of data to read

        Returns:
            Requested data as a list
        """
        if addr > self._woffset:
            logging.info('Read from write address, confirm this is not an error')

        data = self._naeusb.cmdReadMem(addr, readlen)
        return data

    def usb_clk_setenabled(self, status):
        """ Turn on or off the Data Clock to the FPGA """
        if status:
            self._naeusb.sendCtrl(CW305_USB.REQ_SYSCFG, CW305_USB.SYSCFG_CLKON)
        else:
            self._naeusb.sendCtrl(CW305_USB.REQ_SYSCFG, CW305_USB.SYSCFG_CLKOFF)

    def usb_trigger_toggle(self, _=None):
        """ Toggle the trigger line high then low """
        self._naeusb.sendCtrl(CW305_USB.REQ_SYSCFG, CW305_USB.SYSCFG_TOGGLE)

    def vccint_set(self, vccint=1.0):
        """ Set the VCC-INT for the FPGA """

        # print "vccint = " + str(vccint)

        if (vccint < 0.6) or (vccint > 1.15):
            raise ValueError("VCC-Int out of range 0.6V-1.1V")

        # Convert to mV
        vccint = int(vccint * 1000)
        vccsetting = [vccint & 0xff, (vccint >> 8) & 0xff, 0]

        # calculate checksum
        vccsetting[2] = vccsetting[0] ^ vccsetting[1] ^ CW305_USB.VCCINT_XORKEY

        self._naeusb.sendCtrl(CW305_USB.REQ_VCCINT, 0, vccsetting)

        resp = self._naeusb.readCtrl(CW305_USB.REQ_VCCINT, dlen=3)
        if resp[0] != 2:
            raise IOError("VCC-INT Write Error, response = %d" % resp[0])

    def vccint_get(self):
        """ Get the last set value for VCC-INT """

        resp = self._naeusb.readCtrl(CW305_USB.REQ_VCCINT, dlen=3)
        return float(resp[1] | (resp[2] << 8)) / 1000.0

    def _con(self, scope=None, bsfile=None, force=False):
        """Connect to CW305 board, and download bitstream.

        If the target has already been programmed it skips reprogramming
        unless forced.

        Args:
            scope (ScopeTemplate): An instance of a scope object.
            bsfile (path): The path to the bitstream file to program the FPGA with.
            force (bool): Whether or not to force reprogramming.
            force (bool): Whether or not to force reprogramming.
        """

        self._naeusb.con(idProduct=[0xC305])
        if self.fpga.isFPGAProgrammed() == False or force:
            if bsfile is None:
                print("No FPGA Bitstream file specified.")
            elif not os.path.isfile(bsfile):
                print(("FPGA Bitstream not configured or '%s' not a file." % str(bsfile)))
            else:
                from datetime import datetime
                starttime = datetime.now()
                status = self.fpga.FPGAProgram(open(bsfile, "rb"), exceptOnDoneFailure=False)
                stoptime = datetime.now()
                if status:
                    logging.info('FPGA Config OK, time: %s' % str(stoptime - starttime))
                else:
                    logging.warning('FPGA Done pin failed to go high, check bitstream is for target device.')
        self.usb_clk_setenabled(True)
        self.fpga_write(0x100+self._woffset, [0])
        self.pll.cdce906init()

    def _dis(self):
        if self._naeusb:
            self._naeusb.close()

    def checkEncryptionKey(self, key):
        """Validate encryption key"""
        return key

    def loadEncryptionKey(self, key):
        """Write encryption key to FPGA"""
        self.key = key
        key = key[::-1]
        self.fpga_write(0x100+self._woffset, key)

    def loadInput(self, inputtext):
        """Write input to FPGA"""
        self.input = inputtext
        text = inputtext[::-1]
        self.fpga_write(0x200+self._woffset, text)

    def is_done(self):
        """Check if FPGA is done"""
        result = self.fpga_read(0x50, 1)[0]

        if result == 0x00:
            return False
        else:
            # Clear trigger
            self.fpga_write(0x40+self._woffset, [0])
            # LED Off
            self.fpga_write(0x10+self._woffset, [0])
            return True

    isDone = camel_case_deprecated(is_done)

    def readOutput(self):
        """"Read output from FPGA"""
        data = self.fpga_read(0x200, 16)
        data = data[::-1]
        #self.newInputData.emit(util.list2hexstr(data))
        return data

    @property
    def clkusbautooff(self):
        """ If set, the USB clock is automatically disabled on capture.

        The USB clock is re-enabled after self.clksleeptime milliseconds.

        :Getter: Gets whether to turn off the USB clock on capture

        :Setter: Sets whether to turn off the USB clock on capture
        """
        return self._clkusbautooff

    @clkusbautooff.setter
    def clkusbautooff(self, state):
        self._clkusbautooff = state

    @property
    def clksleeptime(self):
        """ Time (in milliseconds) that the USB clock is disabled for upon
        capture, if self.clkusbautooff is set.
        """
        return self._clksleeptime

    @clksleeptime.setter
    def clksleeptime(self, value):
        self._clksleeptime = value

    def go(self):
        """Disable USB clock (if requested), perform encryption, re-enable clock"""
        if self.clkusbautooff:
            self.usb_clk_setenabled(False)

        #LED On
        self.fpga_write(0x10+self._woffset, [0x01])

        time.sleep(0.001)
        self.usb_trigger_toggle()
        # self.FPGAWrite(0x100, [1])
        # self.FPGAWrite(0x100, [0])

        if self.clkusbautooff:
            time.sleep(self.clksleeptime/1000.0)
            self.usb_clk_setenabled(True)

    def simpleserial_read(self, cmd, pay_len, end='\n', timeout=250, ack=True):
        """Read data from target

        Mimics simpleserial protocol of serial based targets

        Args:
            cmd (str): Command to ues. Only accepts 'r' for now.
            pay_len: Unused
            end: Unused
            timeout: Unused
            ack: Unused

        Returns: Value from Crypto output register

        .. versionadded:: 5.1
            Added simpleserial_read to CW305
        """
        if cmd == "r":
            return self.readOutput()
        else:
            raise ValueError("Unknown command {}".format(cmd))

    def simpleserial_write(self, cmd, data, end=None):
        """Write data to target.

        Mimics simpleserial protocol of serial based targets.

        Args:
            cmd (str): Command to use. Target supports 'p' (write plaintext),
                and 'k' (write key).
            data (bytearray): Data to write to target
            end: Unused

        Raises:
            ValueError: Unknown command

        .. versionadded:: 5.1
            Added simpleserial_write to CW305
        """
        if cmd == 'p':
            self.loadInput(data)
            self.go()
        elif cmd == 'k':
            self.loadEncryptionKey(data)
        else:
            raise ValueError("Unknown command {}".format(cmd))

    def set_key(self, key, ack=False, timeout=250):
        """Checks if key is different from the last one sent. If so, send it.

        Args:
            key (bytearray):  key to send
            ack: Unused
            timeout: Unused

        .. versionadded:: 5.1
            Added set_key to CW305
        """
        if self.last_key != key:
            self.last_key = key
            self.simpleserial_write('k', key)
