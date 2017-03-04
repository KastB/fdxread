#!/usr/bin/env python
# .- coding: utf-8 -.
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation version 2 of the License.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License along
#  with this program; if not, write to the Free Software Foundation, Inc.,
#  51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
#  Copyright (C) 2016 Lasse Karstensen
#
"""
Take the output from the fdx decoder and create some rudimentary NMEA0183 from
it.

By feeding this into OpenCPN (via kplex in tcp mode), we
get some visualization.
"""
from __future__ import print_function

import json
import logging
import unittest
from datetime import datetime
from functools import reduce
from operator import xor
from pprint import pprint, pformat
from sys import argv, stdin, stdout, stderr

from LatLon23 import LatLon, Latitude, Longitude


def nmeapos(pos):
    """
    >>> nmeapos(LatLon("54.1024833333", "10.8079"))
    ['5406.15', 'N', '1048.47', 'E']
    """
    assert isinstance(pos, LatLon)

    def fmt(p):
        s = p.to_string("%d")
        assert len(s) >= 1
        decmin = float(p.to_string("%M"))
        assert decmin / 10. <= 60
        s += ("%.2f" % decmin).zfill(5)
        return s

    return [fmt(pos.lat), pos.to_string("H")[0],
            fmt(pos.lon), pos.to_string("H")[1]]


class format_NMEA0183(object):
    gpstime = None
    gpspos = None

    def __init__(self, joinlines=True):
        self.joinlines = joinlines

    def handle(self, sample):
        assert type(sample) == dict
        result = []

        if sample["mdesc"] == "dst200depth":
            # $--DBT,x.x,f,x.x,M,x.x,F*hh<CR><LF>
            result += [("$SDDBT",
                        "",
                        "f",
                        "%s" % sample["depth"],
                        "m",
                        "",
                        "F")]
            # $--VHW,x.x,T,x.x,M,x.x,N,x.x,K*hh<CR><LF>

            result += [("$SDVHW",
                        "0.0",
                        "T",
                        "0.0",
                        "M",
                        "%.2f" % sample["stw"],
                        "N",
                        "0.0",
                        "K")]

        elif sample["mdesc"] == "gpstime":
            # Will be used later on.
            self.gpstime = datetime.strptime(sample["utctime"],
                                             "%Y-%m-%dT%H:%M:%S")

        elif sample["mdesc"] == "gpspos":
            lat = Latitude(sample["lat"])
            lon = Longitude(sample["lon"])
            self.gpspos = LatLon(lat, lon)

        elif sample["mdesc"] == "gpscog":
            if self.gpstime is None or self.gpspos is None:
                # Not enough data yet.
                pass
            else:
                rmc = ["$GPRMC",
                       self.gpstime.strftime("%H%M%S"),
                       "A"]
                rmc += nmeapos(self.gpspos)
                rmc += ["%.2f" % sample["sog"],
                        "%.2f" % sample["cog"],
                        self.gpstime.strftime("%d%m%y"),
                        "0.0",  # magn var
                        "E"]
                result.append(tuple(rmc))

                #  $--HDT,x.x,T*hh<CR><LF>
                result.append(("$GPHDT",
                               "%.2f" % sample["cog"],
                               "T"))

        elif sample["mdesc"] == "gnd10msg3":
            #  $--MWV,x.x,a,x.x,a*hh<CR><LF>
            result += [("$FVMWV",
                        "%.2f" % sample["awa"],
                        "R",  # (R)elative, not (T)rue.
                        "%.2f" % sample["aws_lo"],
                        "K",    # knots
                        "A")   # (valid)
                       ]

        elif sample["mdesc"] == "environment":
            # $IIXDR,P,1.02481,B,Barometer*0D
            # $IIXDR,C,19.52,C,TempAir*3D
            result += [("$ZZXDR",
                        "P",
                        "%.5f" % sample["airpressure"],
                        "B", "Barometer"),
                       ("$ZZXDR",
                        "C",
                        "%.2f" % sample["temp_c"],
                        "C",
                        "TempDir")
                       ]

        else:
            if sample["mdesc"] not in ["emptymsg0", "gpsping", "static1s",
                                       "windsignal", "dst200depth2",
                                       "gnd10msg2", "windmsg3", "wind40s"]:
                logging.warning("Unhandled: '%s'" % pformat(sample))
            else:
                # Ignore known no-ops.
                pass

        result = [",".join(x) for x in result]  # Make it a string.
        return self.checksum(result or None)

    def checksum(self, samples):
        if samples is None:
            return None

        completed = []
        for sentence in samples:
            assert sentence[0] == "$"
            cksum = reduce(xor, (ord(s) for s in sentence[1:]))
            completed.append("%s*%02X" % (sentence, cksum))

        if completed and self.joinlines:
            completed = "\n".join(completed)

        return completed or None


class TestNMEA0183(unittest.TestCase):
    def test_gps(self):
        formatter = format_NMEA0183(joinlines=False)
        r = formatter.handle({"mdesc": "gpspos", "lat": 54.10246, "lon": 10.8079})
        assert r is None
        r = formatter.handle({"utctime": "2017-01-12T19:16:55", "mdesc": "gpstime"})
        assert r is None

        r = formatter.handle({"mdesc": "gpscog", "sog": 0.16, "cog": 344.47058823529414})
        assert len(r) == 2

        assert r[0] == '$GPRMC,191655,A,5406.15,N,1048.47,E,0.16,344.47,120117,0.0,E*47'
        assert r[1] == '$GPHDT,344.47,T*05'

    def test_joining(self):
        formatter = format_NMEA0183(joinlines=True)
        msg = {"mdesc": "environment", "airpressure": 101.42, "temp_c": 21.0}
        r = formatter.handle(msg)
        assert isinstance(r, str)
        assert r == "$ZZXDR,P,101.42000,B,Barometer*21\n$ZZXDR,C,21.00,C,TempDir*10"

def main():
    logging.basicConfig(level=logging.INFO)
    if "--test" in argv:
        argv.pop(argv.index("--test"))
        unittest.main()
        exit()

    formatter = format_NMEA0183(joinlines=False)

    while True:
        line = stdin.readline()
        if len(line) == 0:
            break
        line = line.strip()
        if len(line) <= 2:
            continue
        if line.startswith("#"):
            continue

        try:
            sample = json.loads(line)
        except ValueError:
            logging.error("Invalid JSON: %s" % line)
            continue

        nmealines = formatter.handle(sample)
        if nmealines:
            for line in nmealines:
                print(line)
                stdout.flush()


if __name__ == "__main__":
    main()
