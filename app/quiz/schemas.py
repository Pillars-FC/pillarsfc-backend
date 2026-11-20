from typing import Literal

from pydantic import BaseModel, Field, model_validator


class QuizQuestion(BaseModel):
    id: int
    question: str
    options: list[str]


class QuizQuestionWithAnswer(QuizQuestion):
    answer: str


class QuizResponse(BaseModel):
    status: Literal["success"]
    data: list[QuizQuestion]


class QuizAnswerSubmission(BaseModel):
    question_id: int
    selected_answer: str


class QuizSubmission(BaseModel):
    answers: list[QuizAnswerSubmission] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_unique_question_ids(self) -> "QuizSubmission":
        question_ids = [answer.question_id for answer in self.answers]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Each question may only be answered once")
        return self


class QuizScore(BaseModel):
    score: int
    total: int


class QuizScoreResponse(BaseModel):
    status: Literal["success"]
    data: QuizScore
