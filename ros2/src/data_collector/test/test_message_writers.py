import numpy as np
import pytest
import sensor_msgs_py.point_cloud2 as pc2
from sensor_msgs.msg import PointField
from std_msgs.msg import Header

from data_collector.message_writers import _pointcloud_to_array


def test_pointcloud_to_array_accepts_xyz_without_color_fields() -> None:
    message = pc2.create_cloud_xyz32(Header(), [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])

    points = _pointcloud_to_array(message, num_points=3)

    np.testing.assert_allclose(
        points,
        np.array(
            [
                [1.0, 2.0, 3.0, 0.0, 0.0, 0.0],
                [4.0, 5.0, 6.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        ),
    )


def test_pointcloud_to_array_accepts_packed_rgba_field() -> None:
    fields = [
        PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
        PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
        PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
        PointField(name="rgba", offset=12, datatype=PointField.UINT32, count=1),
    ]
    message = pc2.create_cloud(Header(), fields, [(1.0, 2.0, 3.0, 0x11223344)])

    points = _pointcloud_to_array(message, num_points=1)

    np.testing.assert_allclose(points[0], np.array([1.0, 2.0, 3.0, 0x22, 0x33, 0x44]))


def test_pointcloud_to_array_reports_missing_position_fields() -> None:
    fields = [
        PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
        PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
    ]
    message = pc2.create_cloud(Header(), fields, [(1.0, 2.0)])

    with pytest.raises(ValueError, match="missing required field"):
        _pointcloud_to_array(message, num_points=1)
