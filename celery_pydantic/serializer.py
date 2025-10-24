import datetime
import importlib
import json
import uuid

from dataclasses import is_dataclass

from celery import Celery
from kombu.serialization import register
from pydantic import BaseModel, TypeAdapter


model_registry: dict[str, type[BaseModel]] = {}


class PydanticSerializer(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, BaseModel):
            return json.loads(obj.model_dump_json(by_alias=True)) | {
                "__module_path__": f"{obj.__class__.__module__}.{obj.__class__.__name__}"
            }
        elif is_dataclass(obj):
            ta = TypeAdapter(obj.__class__)
            return ta.dump_python(obj, mode="json") | {
                "__module_path__": f"{obj.__class__.__module__}.{obj.__class__.__name__}"
            }
        elif isinstance(obj, datetime.date):
            return {"__isoformat__": obj.__class__.__name__, "value": obj.isoformat()}
        elif isinstance(obj, uuid.UUID):
            return str(obj)

        return obj


def pydantic_decoder(obj):
    if "__isoformat__" in obj:
        typ = getattr(datetime, obj["__isoformat__"])
        return typ.fromisoformat(obj["value"])

    elif "__module_path__" in obj:
        if obj["__module_path__"] not in model_registry:
            module_path = ".".join(obj["__module_path__"].split(".")[:-1])
            cls_name = obj["__module_path__"].split(".")[-1]
            model_module = importlib.import_module(module_path)
            cls = getattr(model_module, cls_name)
            model_registry[obj["__module_path__"]] = cls

        cls = model_registry[obj["__module_path__"]]
        if issubclass(cls, BaseModel):
            if getattr(cls, "model_config", {}).get("extra") == "forbid":
                obj.pop("__module_path__")

            return cls.model_validate(obj, by_alias=True)

        elif is_dataclass(cls):
            ta = TypeAdapter(cls)
            return ta.validate_python(obj)

    return obj


# Encoder function
def pydantic_dumps(obj):
    return json.dumps(obj, cls=PydanticSerializer)


# Decoder function
def pydantic_loads(obj):
    return json.loads(obj, object_hook=pydantic_decoder)


def pydantic_celery(celery_app: Celery):
    register(
        "pydantic",
        pydantic_dumps,
        pydantic_loads,
        content_type="application/x-pydantic",
        content_encoding="utf-8",
    )

    celery_app.conf.update(
        task_serializer="pydantic",
        result_serializer="pydantic",
        event_serializer="pydantic",
        accept_content=["application/json", "application/x-pydantic"],
        result_accept_content=["application/json", "application/x-pydantic"],
    )
