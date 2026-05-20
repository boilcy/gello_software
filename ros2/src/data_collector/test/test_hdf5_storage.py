import h5py
import numpy as np

from data_collector.hdf5_storage import Hdf5EpisodeStorage


def test_hdf5_storage_appends_arrays_and_embedded_null_bytes(tmp_path) -> None:
    filename = tmp_path / "episode.hdf5"
    storage = Hdf5EpisodeStorage(str(filename), compression=None, mode="w")

    storage.append_array("sample_time_ns", np.asarray(100, dtype=np.int64))
    storage.append_array("sample_time_ns", np.asarray(200, dtype=np.int64))
    storage.append_bytes("encoded/payload", b"a\0b")
    storage.append_bytes("encoded/payload", b"longer-payload")
    storage.write_attr("encoded/payload", "writer", "test")
    storage.write_json("metadata/collector/config_json", {"ok": True})
    storage.close()

    with h5py.File(filename, "r") as hdf5_file:
        assert hdf5_file["sample_time_ns"][:].tolist() == [100, 200]
        assert hdf5_file["encoded/payload"][0].rstrip(b"\0") == b"a\0b"
        assert hdf5_file["encoded/payload"][1].rstrip(b"\0") == b"longer-payload"
        assert hdf5_file["encoded/payload"].attrs["writer"] == "test"
        assert hdf5_file["metadata/collector/config_json"][()].decode("utf-8") == '{"ok":true}'
