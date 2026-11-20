import json
import random
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.quiz.schemas import (
    QuizQuestion,
    QuizQuestionWithAnswer,
    QuizResponse,
    QuizScoreResponse,
    QuizSubmission,
)

QUIZ_FILE = Path(__file__).with_name("football_quiz.json")
QUESTION_COUNT = 5

quiz_router = APIRouter()


def load_questions() -> list[QuizQuestionWithAnswer]:
    with QUIZ_FILE.open("r", encoding="utf-8") as file:
        questions = json.load(file)

    if not isinstance(questions, list) or len(questions) < QUESTION_COUNT:
        raise RuntimeError(
            f"The quiz JSON file must contain at least {QUESTION_COUNT} questions"
        )

    return [QuizQuestionWithAnswer.model_validate(question) for question in questions]


@quiz_router.get(
    "",
    summary="Get five random quiz questions",
    response_model=QuizResponse,
    status_code=status.HTTP_200_OK,
)
async def get_quiz_questions() -> QuizResponse:
    selected_questions = random.sample(load_questions(), k=QUESTION_COUNT)
    return QuizResponse(
        status="success",
        data=[
            QuizQuestion(
                id=question.id,
                question=question.question,
                options=question.options,
            )
            for question in selected_questions
        ],
    )


@quiz_router.post(
    "/score",
    summary="Score submitted quiz answers",
    response_model=QuizScoreResponse,
    status_code=status.HTTP_200_OK,
)
async def score_quiz(submission: QuizSubmission) -> QuizScoreResponse:
    questions = {question.id: question for question in load_questions()}
    score = 0

    for submitted_answer in submission.answers:
        question = questions.get(submitted_answer.question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown question ID: {submitted_answer.question_id}",
            )
        if submitted_answer.selected_answer not in question.options:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Selected answer is not an option for question "
                    f"{submitted_answer.question_id}"
                ),
            )
        score += submitted_answer.selected_answer == question.answer

    return QuizScoreResponse(
        status="success",
        data={"score": score, "total": len(submission.answers)},
    )
