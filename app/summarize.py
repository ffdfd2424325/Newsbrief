import re
import math
from typing import Optional, List, Tuple
from collections import Counter
import nltk
from nltk.tokenize import sent_tokenize
from nltk.corpus import stopwords
import ssl

# Загружаем необходимые ресурсы NLTK
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# Пытаемся скачать необходимые ресурсы NLTK
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords', quiet=True)

# Русские стоп-слова
RUSSIAN_STOPWORDS = set([
    'и', 'в', 'не', 'на', 'с', 'по', 'для', 'к', 'из', 'от', 'за', 'как', 'что', 'это',
    'а', 'но', 'или', 'если', 'то', 'все', 'его', 'её', 'их', 'мы', 'вы', 'они', 'он', 'она',
    'оно', 'тот', 'та', 'те', 'был', 'была', 'было', 'есть', 'будет', 'быть', 'уже', 'ещё',
    'также', 'только', 'ещё', 'очень', 'сам', 'свою', 'свой', 'своего', 'своей', 'своих',
    'своём', 'своя', 'свои', 'своим', 'своими', 'сами', 'само', 'самой', 'самого', 'самом'
])

# Разделители предложений для русского языка
SENTENCE_END = re.compile(r"(?<=[\.!?])\s+")

# Аббревиатуры для избежания разбиения
ABBREVIATIONS = {
    "т.д.", "т.п.", "г.", "ул.", "пр.", "стр.", "рис.", "им.", "акад.",
    "Mr.", "Ms.", "Dr.", "Inc.", "Ltd.", "e.g.", "i.e.", "p.m.", "a.m.",
    "т.е.", "т.к.", "и т.д.", "и т.п.", "др.", "проф.", "доц.", "канд.",
}

def _normalize_whitespace(text: str) -> str:
    """Нормализует пробелы в тексте"""
    return re.sub(r"\s+", " ", text or "").strip()

def _split_sentences_ru(text: str) -> List[str]:
    """Разбивает текст на предложения с учетом русских аббревиатур"""
    parts = SENTENCE_END.split(text)
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Проверяем, не является ли предыдущее предложение аббревиатурой
        if out and any(out[-1].endswith(abbr.rstrip('.')) or out[-1].endswith(abbr) for abbr in ABBREVIATIONS):
            out[-1] = (out[-1] + " " + p).strip()
        else:
            out.append(p)
    return out

def _tokenize_text(text: str) -> List[str]:
    """Токенизирует текст, удаляя пунктуацию и приводя к нижнему регистру"""
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    words = text.split()
    return [word for word in words if len(word) > 2]

def _compute_tf_idf(sentences: List[str], all_sentences: List[str]) -> List[float]:
    """Вычисляет TF-IDF score для предложений"""
    if not sentences:
        return []

    # Создаем словарь всех слов в документе
    all_words = Counter()
    for sent in all_sentences:
        words = _tokenize_text(sent)
        all_words.update(words)

    # Вычисляем IDF для каждого слова
    total_sentences = len(all_sentences)
    idf_scores = {}
    for word in all_words:
        # Количество предложений, содержащих это слово
        sent_with_word = sum(1 for sent in all_sentences if word in _tokenize_text(sent))
        idf_scores[word] = math.log(total_sentences / (1 + sent_with_word))

    # Вычисляем TF-IDF для каждого предложения
    tfidf_scores = []
    for sentence in sentences:
        words = _tokenize_text(sentence)
        if not words:
            tfidf_scores.append(0.0)
            continue

        # TF для предложения
        word_counts = Counter(words)
        total_words = len(words)

        # TF-IDF score
        score = 0.0
        for word in words:
            if word in idf_scores:
                tf = word_counts[word] / total_words
                score += tf * idf_scores[word]

        tfidf_scores.append(score)

    return tfidf_scores

def _score_sentence_advanced(s: str, position: int, total: int) -> float:
    """Расширенная оценка предложения для суммирования"""
    s_clean = _normalize_whitespace(s)
    length = len(s_clean)

    if length < 20:  # Слишком короткое предложение
        return -1000

    # Оценка длины (оптимально 80-200 символов)
    length_score = 1.0 - abs(140 - length) / 200.0

    # Оценка позиции (первые предложения важнее)
    position_score = max(0, 1.0 - (position / total) * 0.3)

    # Наличие цифр (факты, даты)
    digits_bonus = 10 if re.search(r'[0-9]', s_clean) else 0

    # Наличие заглавных букв (имена, названия)
    caps_bonus = 5 if re.search(r'[А-ЯA-Z]{3,}', s_clean) else 0

    # Наличие ключевых слов (факты, действия)
    keywords = ['заявил', 'сообщил', 'стало', 'будет', 'стал', 'стала', 'стали',
                'составил', 'достиг', 'увеличил', 'снижил', 'принял', 'решил']
    keyword_bonus = sum(5 for keyword in keywords if keyword in s_clean.lower())

    # Штраф за шаблонные фразы
    boilerplate_penalty = 0
    boilerplate_phrases = ['подробнее', 'читать дальше', 'источник', '©', 'подписывайтесь']
    for phrase in boilerplate_phrases:
        if phrase in s_clean.lower():
            boilerplate_penalty -= 20

    return length_score * 10 + position_score * 5 + digits_bonus + caps_bonus + keyword_bonus + boilerplate_penalty

def smart_extract_summary(text: str, max_sentences: int = 3) -> str:
    """Умное извлечение суммирования с использованием TF-IDF и эвристик"""
    if not text:
        return ""

    # Очищаем текст
    cleaned = _normalize_whitespace(text)

    # Разбиваем на предложения
    sentences = _split_sentences_ru(cleaned)

    if not sentences:
        return cleaned[:400] + ("…" if len(cleaned) > 400 else "")

    # Фильтруем предложения (убираем слишком короткие и шаблонные)
    filtered = []
    for i, sent in enumerate(sentences):
        sent_clean = sent.strip()
        if len(sent_clean) >= 30 and not _is_boilerplate(sent_clean):
            filtered.append((i, sent_clean))

    if not filtered:
        # Если все предложения отфильтрованы, берем первые 3
        selected = sentences[:max_sentences]
        result = " ".join(selected)
        return result[:500] + ("…" if len(result) > 500 else "")

    # Если предложений мало, берем все
    if len(filtered) <= max_sentences:
        selected = [sent for _, sent in filtered]
        result = " ".join(selected)
        return result[:600] + ("…" if len(result) > 600 else "")

    # Вычисляем TF-IDF score для предложений
    original_sentences = [sent for _, sent in filtered]
    tfidf_scores = _compute_tf_idf(original_sentences, original_sentences)

    # Считаем позиции и дополнительные оценки
    scored_sentences = []
    for i, (orig_idx, sentence) in enumerate(filtered):
        tfidf_score = tfidf_scores[i] if i < len(tfidf_scores) else 0
        position_score = _score_sentence_advanced(sentence, orig_idx, len(sentences))
        total_score = tfidf_score * 0.3 + position_score * 0.7
        scored_sentences.append((total_score, sentence))

    # Сортируем по оценке и берем топ-N
    scored_sentences.sort(key=lambda x: x[0], reverse=True)
    selected = [sentence for _, sentence in scored_sentences[:max_sentences]]

    # Восстанавливаем оригинальный порядок
    final_sentences = []
    for sent in sentences:
        if sent in selected:
            final_sentences.append(sent)

    result = " ".join(final_sentences)

    # Ограничиваем длину
    if len(result) > 600:
        result = result[:600].rstrip() + "…"

    return result

def _is_boilerplate(s: str) -> bool:
    """Проверяет, является ли предложение шаблонным"""
    s_low = s.lower()
    boilerplate_patterns = [
        r"подробнее", r"читать дальше", r"читать далее", r"подписывайтесь",
        r"источник:", r"©", r"телеграм", r"t\.me/", r"twitter", r"facebook",
        r"фото:", r"видео:", r"смотрите также", r"рассказали", r"сообщили",
        r"по материалам", r"как пишет", r"как сообщили"
    ]
    return any(re.search(p, s_low) for p in boilerplate_patterns)

def summarize(text: str) -> str:
    """Основная функция суммирования"""
    return smart_extract_summary(text, max_sentences=3)
