from __future__ import annotations

import json
import os
from importlib import import_module
from typing import Any

import numpy as np


class Hdf5EpisodeStorage:
    """Append-oriented HDF5 adapter used by streaming message writers."""

    def __init__(
        self,
        target: str | Any,
        compression: str | None = "gzip",
        mode: str = "a",
    ):
        self.compression = compression
        self._owns_file = isinstance(target, str)
        if self._owns_file:
            directory = os.path.dirname(target)
            if directory:
                os.makedirs(directory, exist_ok=True)
            h5py = import_module("h5py")
            self._hdf5_file = h5py.File(target, mode)
        else:
            self._hdf5_file = target

    @property
    def hdf5_file(self) -> Any:
        return self._hdf5_file

    def append_array(self, path: str, value: np.ndarray) -> Any:
        parent, name = split_hdf5_path(path)
        group = self.require_group(parent) if parent else self._hdf5_file
        array = np.asarray(value)

        if name not in group:
            dataset = group.create_dataset(
                name,
                shape=(0, *array.shape),
                maxshape=(None, *array.shape),
                chunks=True,
                dtype=array.dtype,
                compression=self.compression,
            )
        else:
            dataset = group[name]

        if dataset.attrs.get("_streaming_vlen"):
            dataset.resize((dataset.shape[0] + 1,))
            dataset[-1] = np.asarray(array, dtype=np.float64).reshape(-1)
            return dataset

        if dataset.shape[1:] != array.shape:
            dataset = self._convert_dataset_to_vlen(group, name, dataset)
            dataset.resize((dataset.shape[0] + 1,))
            dataset[-1] = np.asarray(array, dtype=np.float64).reshape(-1)
            return dataset

        dataset.resize((dataset.shape[0] + 1, *dataset.shape[1:]))
        dataset[-1] = array
        return dataset

    def append_bytes(self, path: str, payload: bytes) -> Any:
        parent, name = split_hdf5_path(path)
        group = self.require_group(parent) if parent else self._hdf5_file
        capacity = _bytes_capacity(len(payload))

        if name not in group:
            dataset = group.create_dataset(
                name,
                shape=(0,),
                maxshape=(None,),
                chunks=True,
                dtype=f"S{capacity}",
                compression=self.compression,
            )
        else:
            dataset = group[name]
            if dataset.dtype.kind != "S":
                raise TypeError(f"Dataset '{path}' is not a fixed-width byte dataset.")
            if len(payload) > dataset.dtype.itemsize:
                dataset = self._grow_fixed_bytes_dataset(group, name, dataset, len(payload))

        dataset.resize((dataset.shape[0] + 1,))
        dataset[-1] = np.bytes_(payload)
        return dataset

    def write_attr(self, path: str, key: str, value: Any) -> None:
        self.get(path).attrs[key] = value

    def append_csv_attr(self, path: str, key: str, value: str) -> None:
        target = self.get(path)
        values = set(filter(None, str(target.attrs.get(key, "")).split(",")))
        values.add(value)
        target.attrs[key] = ",".join(sorted(values))

    def write_json(self, path: str, payload: dict[str, Any]) -> None:
        parent, name = split_hdf5_path(path)
        group = self.require_group(parent) if parent else self._hdf5_file
        if name in group:
            del group[name]
        config_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        group.create_dataset(name, data=np.bytes_(config_json.encode("utf-8")))

    def require_group(self, path: str) -> Any:
        group = self._hdf5_file
        for part in (part for part in path.split("/") if part):
            group = group.require_group(part)
        return group

    def get(self, path: str) -> Any:
        clean_path = path.strip("/")
        return self._hdf5_file[clean_path] if clean_path else self._hdf5_file

    def flush(self) -> None:
        self._hdf5_file.flush()

    def close(self) -> None:
        if self._owns_file:
            self._hdf5_file.close()

    def _convert_dataset_to_vlen(self, group: Any, name: str, dataset: Any) -> Any:
        h5py = import_module("h5py")
        attrs = dict(dataset.attrs.items())
        values = [
            np.asarray(dataset[index], dtype=np.float64).reshape(-1)
            for index in range(dataset.shape[0])
        ]
        del group[name]
        converted = group.create_dataset(
            name,
            shape=(len(values),),
            maxshape=(None,),
            chunks=True,
            dtype=h5py.vlen_dtype(np.dtype("float64")),
            compression=self.compression,
        )
        for index, value in enumerate(values):
            converted[index] = value
        for key, value in attrs.items():
            converted.attrs[key] = value
        converted.attrs["_streaming_vlen"] = True
        return converted

    def _grow_fixed_bytes_dataset(
        self,
        group: Any,
        name: str,
        dataset: Any,
        required_size: int,
    ) -> Any:
        attrs = dict(dataset.attrs.items())
        data = dataset[:]
        capacity = _bytes_capacity(required_size, current=dataset.dtype.itemsize)
        del group[name]
        grown = group.create_dataset(
            name,
            data=data.astype(f"S{capacity}"),
            maxshape=(None,),
            chunks=True,
            compression=self.compression,
        )
        for key, value in attrs.items():
            grown.attrs[key] = value
        return grown


def split_hdf5_path(path: str) -> tuple[str, str]:
    clean_path = path.strip("/")
    parent, _, name = clean_path.rpartition("/")
    if not name:
        raise ValueError(f"HDF5 path '{path}' does not name a dataset.")
    return parent, name


def _bytes_capacity(size: int, current: int = 0) -> int:
    capacity = max(1, current)
    required = max(1, size)
    while capacity < required:
        capacity *= 2
    return capacity
