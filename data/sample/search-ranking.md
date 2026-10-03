# Search ranking

An inverted index maps each word to the documents that contain it. Sorted posting
lists can be intersected for queries requiring every word, or merged for queries
that accept any word.

TF-IDF gives more weight to informative terms. Cosine similarity compares the
weighted query with a document while accounting for document length. A heap keeps
the best results without sorting every matching document.
