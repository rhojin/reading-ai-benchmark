Book: $book_title by $book_author
Chapter $chapter_no: $chapter_title

Story so far (short summaries of the earlier chapters):
$story_so_far

<chapter>
$chapter_text
</chapter>

Write the 6 questions for this chapter. If there are earlier chapters, at least one "hard" question should connect this chapter with something from the story so far.

Also write "chapter_summary": 2-3 sentences about what happens in this chapter. It becomes part of the "story so far" for the next chapter.

Reply with JSON in exactly this shape (2 easy, 2 medium, 2 hard):
{"questions": [{"level": "easy", "question": "...", "answer": "..."}, ...], "chapter_summary": "..."}
