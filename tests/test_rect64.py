# python3 -m unittest rect64_test

import unittest

from picasa2digikam.rect64 import parse_hexfloat, parse_rect64, to_digikam_rect


class TestRect64Parser(unittest.TestCase):
    def test_parse_hexfloat(self):
        self.assertAlmostEqual(0.24810791015625, parse_hexfloat('3f84'))
        self.assertAlmostEqual(0.3585662841796875, parse_hexfloat('5bcb'))
        self.assertAlmostEqual(0.3486480712890625, parse_hexfloat('5941'))
        self.assertAlmostEqual(0.5196380615234375, parse_hexfloat('8507'))

    def test_parse_rect64(self):
        actual = parse_rect64('rect64(3f845bcb59418507)')
        self.assertEqual(4, len(actual))
        self.assertAlmostEqual(0.24810791015625, actual[0])
        self.assertAlmostEqual(0.3585662841796875, actual[1])
        self.assertAlmostEqual(0.3486480712890625, actual[2])
        self.assertAlmostEqual(0.5196380615234375, actual[3])

    def test_to_digikam_rect_no_rotation(self):
        # Image ID 38, IMG_20200720_103203.jpg has resolution 3024x4032, orientation 0.
        self.assertEqual('<rect x="264" y="1449" width="382" height="458"/>',
                         to_digikam_rect((3024, 4032, 0), parse_rect64('rect64(166f5c0036db7924)')))

    def test_to_digikam_rect_180_rotation(self):
        # Image ID 3, 20200720_130240.jpg has resolution 4608x3456, orientation 3.
        # In Photoshop, Picasa's face is roughly at x1=2132 (0.462), x2=2992 (0.649), y1=1172 (0.339), y2=2232 (0.645).
        # But Picasa outputs (left=0.350, right=0.542, top=0.356, bottom=0.663).
        # Orientation 3 means a 180º rotation. So we have:
        #   x1_new = 1-x2 = 0.351 = 1617
        #   x2_new = 1-x1 = 0.537 = 2474
        #   y1_new = 1-y2 = 0.355 = 1227
        #   y2_new = 1-y1 = 0.661 = 2284
        #   x_diff = 857, y_diff = 1057
        #
        # In Photoshop, digiKam's face is roughly at x1=2292, x2=2856, y1=1372, y2=2196
        # And digiKam stores x="2289" y="1373" width="568" height="818" => x2=2857, y2=2191, so that matches well.
        #
        # The two face regognition engines produce different coordinates for the faces, of course, but the mapping seems
        # to be correct. Picasa's face is indeed taller and wider (Photoshop confirms that).
        self.assertEqual('<rect x="2108" y="1164" width="883" height="1058"/>',
                         to_digikam_rect((4608, 3456, 3), parse_rect64('rect64(59c75b558ae3a9c6)')))

    def test_to_digikam_rect_90_rotation(self):
        # Image ID 293, DSC06287.JPG has resolution 3264x4912, orientation 6.
        # Picasa says rect64(34009caa6232b668) -> (left=0.203, top=0.611, right=0.383, bottom=0.712).
        # A manually added digiKam tag gives <rect x="1405" y="661" width="476" height="582"/>.
        self.assertEqual('<rect x="1412" y="663" width="493" height="588"/>',
                         to_digikam_rect((3264, 4912, 6), parse_rect64('rect64(34009caa6232b668)')))

    def test_to_digikam_rect_270_rotation(self):
        # Image ID 135, DSC02676.JPG has resolution 4912x3264, orientation 8.
        # Picasa says rect64(8d22b337991ec231) -> (left=0.551, top=0.700, right=0.598, bottom=0.758).
        # A manually added digiKam tag gives <rect x="2291" y="1975" width="183" height="229"/>, matching Photoshop.
        self.assertEqual('<rect x="2284" y="1974" width="190" height="229"/>',
                         to_digikam_rect((4912, 3264, 8), parse_rect64('rect64(8d22b337991ec231)')))

    def test_to_digikam_rect_short_hex(self):
        # Image ID 254, DSC00040.JPG has resolution 2304x1296, orientation 1.
        self.assertEqual('<rect x="0" y="0" width="670" height="720"/>',
                         to_digikam_rect((2304, 1296, 1), parse_rect64('rect64(4a8e8e6b)')))


if __name__ == '__main__':
    unittest.main()
