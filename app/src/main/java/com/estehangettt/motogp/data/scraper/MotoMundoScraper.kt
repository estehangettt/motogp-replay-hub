package com.estehangettt.motogp.data.scraper

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.jsoup.Jsoup

class MotoMundoScraper {
    suspend fun findEventUrl(country: String, year: Int): String? = withContext(Dispatchers.IO) {
        try {
            val searchUrl = "https://motomundo.net/?s=motogp+$year+$country"
            val doc = Jsoup.connect(searchUrl)
                .userAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                .timeout(10000)
                .get()

            val links = doc.select("a[href]")
            for (link in links) {
                val href = link.attr("href")
                if (href.contains("motogp-$year", ignoreCase = true) && 
                    href.contains("watch-online", ignoreCase = true) &&
                    href.contains(country, ignoreCase = true)) {
                    return@withContext href
                }
            }
            null
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }

    suspend fun getEmbedUrl(motomundoUrl: String, sessionKeyword: String): String? = withContext(Dispatchers.IO) {
        try {
            val doc = Jsoup.connect(motomundoUrl)
                .userAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                .timeout(10000)
                .get()

            val detailsList = doc.select("details")
            for (details in detailsList) {
                val summary = details.selectFirst("summary")?.text() ?: continue
                if (summary.contains(sessionKeyword, ignoreCase = true)) {
                    val iframes = details.select("iframe")
                    for (iframe in iframes) {
                        val src = iframe.attr("data-src").ifEmpty { iframe.attr("src") }
                        if (src.contains("lplaygo") || src.contains("motomundo.top")) {
                            return@withContext src
                        }
                    }
                }
            }
            null
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }
}
