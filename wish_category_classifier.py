# -*- coding: utf-8 -*-
"""
위시 카테고리 분류기
======================

위시 제목(title)만 보고, 미리 정해둔 카테고리 목록 중 하나로 분류한다.
카테고리별 대표 키워드와 위시 제목 사이의 텍스트 유사도(TF-IDF 문자 n-gram + 코사인 유사도)로 분류하는 가벼운 방식이라 실시간으로 1건씩 호출해도 부담이 없다.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ---------------------------------------------------------------------------
# 1. 카테고리별 대표 키워드
#    실제 데이터를 보면서 계속 보강해야하는 부분.
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "패션": [
        "신발", "슬리퍼", "샌들",
        "가방", "백팩", "지갑", "모자", "옷", "티셔츠", "후드티", "자켓", "패딩",
        "바지", "양말", "액세서리", "시계", "벨트", "귀걸이", "목걸이",
    ],
    "문구": [
        "필통", "연필", "볼펜", "샤프", "노트", "다이어리", "플래너",
        "색연필", "지우개", "자", "클립", "포스트잇", "스케치북", "형광펜",
    ],
    "전자기기": [
        "태블릿", "헤드폰", "이어폰", "스마트워치", "블루투스", "스피커",
        "노트북", "카메라", "충전기", "키보드", "마우스", "전자사전", "휴대폰",
    ],
    "취미": [
        "캠핑용품", "텐트", "낚시", "보드게임", "퍼즐", "여행", "콘서트", "캠프",
        "레고", "악기", "기타", "드럼", "피아노", "우쿨렐레", "드론", "프라모델",
    ],
    "스포츠": [
        "축구화", "농구화", "운동화", "축구공", "농구공", "배드민턴", "라켓",
        "자전거", "킥보드", "인라인스케이트", "스케이트보드", "헬멧",
        "줄넘기", "훌라후프", "요가매트", "덤벨", "야구글러브", "배트",
        "축구", "농구", "야구", "운동",
    ],
    "게임": [
        "게임기", "콘솔", "닌텐도", "플레이스테이션", "스위치", "게임타이틀",
        "게임머니", "게임아이템", "쿠폰", "스팀", "롤", "배그",
    ],
    "도서": [
        "책", "소설", "만화책", "참고서", "문제집", "전집", "동화책", "잡지",
        "책세트", "교재",
    ],
    "뷰티": [
        "화장품", "향수", "립밤", "틴트", "스킨케어", "헤어롤", "드라이기",
        "고데기", "네일", "쿠션", "선크림",
    ],
    "굿즈": [
        "포토카드", "피규어", "인형", "캐릭터굿즈", "아이돌굿즈", "포스터",
        "키링", "스티커", "포켓몬카드", "포켓몬 카드", "앨범", "콘서트굿즈",
    ],
    "생활용품": [
        "침구", "수건", "컵", "텀블러", "우산", "파우치", "정리함", "조명",
        "무드등", "가습기", "쿠션", "방석",
    ],
    "기타": [
        "체험", "티켓", "선물",
    ],
}


# ---------------------------------------------------------------------------
# 2. 벡터라이저 지연 초기화 (모듈 최초 사용 시 한 번만 fit, 이후 재사용)
# ---------------------------------------------------------------------------

_vectorizer: Optional[TfidfVectorizer] = None
_category_vectors = None
_category_names: list[str] = []


def _ensure_fitted() -> None:
    global _vectorizer, _category_vectors, _category_names
    if _vectorizer is not None:
        return

    _category_names = list(CATEGORY_KEYWORDS.keys())
    documents = [" ".join(keywords) for keywords in CATEGORY_KEYWORDS.values()]

    # 문자 단위 2~3-gram: 형태소 분석기 없이도 한국어 부분 문자열 유사도를 잘 잡아낸다.
    # (예: "축구화"와 "축구공"이 자모 단위가 아니라 음절 단위로 겹치는 부분이 있음을 인식)
    _vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3))
    _category_vectors = _vectorizer.fit_transform(documents)


def reset_classifier() -> None:
    """CATEGORY_KEYWORDS를 수정한 뒤 다시 학습하고 싶을 때 호출."""
    global _vectorizer, _category_vectors, _category_names
    _vectorizer = None
    _category_vectors = None
    _category_names = []


# ---------------------------------------------------------------------------
# 3. 분류 함수
# ---------------------------------------------------------------------------

DEFAULT_MIN_SIMILARITY = 0.05  # 이보다 유사도가 낮으면 '기타'로 분류


def classify_wish_category(title: str, min_similarity: float = DEFAULT_MIN_SIMILARITY) -> str:
    """위시 제목 하나를 카테고리 하나로 분류. 실시간 단건 호출용."""
    _ensure_fitted()
    title_vec = _vectorizer.transform([title])
    sims = cosine_similarity(title_vec, _category_vectors)[0]
    best_idx = int(np.argmax(sims))
    if sims[best_idx] < min_similarity:
        return "기타"
    return _category_names[best_idx]


def classify_wish_category_with_score(
    title: str, min_similarity: float = DEFAULT_MIN_SIMILARITY
) -> tuple[str, float]:
    """카테고리와 함께 유사도 점수도 반환 (키워드 튜닝용)."""
    _ensure_fitted()
    title_vec = _vectorizer.transform([title])
    sims = cosine_similarity(title_vec, _category_vectors)[0]
    best_idx = int(np.argmax(sims))
    score = float(sims[best_idx])
    category = "기타" if score < min_similarity else _category_names[best_idx]
    return category, score


def classify_wish_categories_batch(
    titles: list[str], min_similarity: float = DEFAULT_MIN_SIMILARITY
) -> list[str]:
    """여러 위시 제목을 한 번에 분류 (배치 재분류용). 단건 호출을 여러 번 하는 것보다 빠르다."""
    _ensure_fitted()
    vecs = _vectorizer.transform(titles)
    sims = cosine_similarity(vecs, _category_vectors)
    results = []
    for row in sims:
        best_idx = int(np.argmax(row))
        results.append(_category_names[best_idx] if row[best_idx] >= min_similarity else "기타")
    return results


if __name__ == "__main__":
    sample_titles = [
        "나이키 축구화", "보스 헤드폰", "캠핑용품", "삼성 태블릿", "포켓몬 카드",
        "보드게임", "피규어", "운동화", "게임기", "자전거", "악기", "책세트",
        "롬앤 틴트", "무드등", "콘서트 티켓",
    ]
    for title in sample_titles:
        category, score = classify_wish_category_with_score(title)
        print(f"{title:12s} -> {category:8s} (유사도 {score:.3f})")