from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
ShortText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Brief(StrictModel):
    topic: Text
    audience: ShortText = "Grand public"
    tone: ShortText = "Narratif et accessible"
    duration_seconds: int = Field(default=60, strict=True, ge=15, le=180)
    scene_count: int = Field(default=3, strict=True, ge=1, le=6)
    genre: Literal["legend", "fiction", "documentary"] = "legend"
    sources: list[Text] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def bound_context(self):
        if len(self.topic) + sum(map(len, self.sources)) > 12000:
            raise ValueError("Contexte du brief trop long.")
        if self.scene_count > self.duration_seconds:
            raise ValueError("Durée insuffisante pour les scènes.")
        return self


class Analysis(StrictModel):
    angle: ShortText
    message: Text
    historical_checks: list[Text] = Field(max_length=12)


class Scene(StrictModel):
    title: ShortText
    duration_seconds: int = Field(strict=True, ge=1, le=180)
    narration: Text
    visual_description: Text
    characters: list[ShortText] = Field(max_length=12)
    landscape: ShortText
    colors: list[ShortText] = Field(min_length=1, max_length=8)
    shot: ShortText
    emotion: ShortText
    sound: ShortText
    image_prompt: Text


class Storyboard(StrictModel):
    title: ShortText
    synopsis: Text
    scenes: list[Scene] = Field(min_length=1, max_length=6)

    def validate_brief(self, brief: Brief):
        if len(self.scenes) != brief.scene_count:
            raise ValueError("scene_count_mismatch")
        if sum(scene.duration_seconds for scene in self.scenes) != brief.duration_seconds:
            raise ValueError("duration_mismatch")
