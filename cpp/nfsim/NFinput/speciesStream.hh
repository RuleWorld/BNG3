#ifndef NFINPUT_SPECIESSTREAM_HH_
#define NFINPUT_SPECIESSTREAM_HH_

#include <cstdio>
#include <string>
#include <utility>
#include <vector>

namespace NFinput {

/*! Byte range of one <Species> element within the source XML file. */
struct SpeciesSpan {
	long long start;   //!< offset of the '<' that opens <Species ...>
	long long length;  //!< bytes through the matching '>' of </Species> or '/>'
};

/*! Streaming pre-pass over a BNG-XML file.
 *
 * NFsim historically did `TiXmlDocument doc(file); doc.LoadFile();`, which
 * materializes the whole document as a DOM before any parsing happens.  For
 * models whose seed state is a long explicit polymer chain, <ListOfSpecies>
 * is essentially the entire file, and the DOM costs roughly ten bytes of
 * resident memory per byte of XML.
 *
 * This pass reads the file once with a small fixed buffer and produces:
 *   - `skeleton`: the complete document with the *interior* of
 *     <ListOfSpecies> removed, so the open/close tags remain and every other
 *     section (parameters, molecule types, rules, observables, functions) is
 *     intact.  The existing DOM parser runs against this unchanged.
 *   - `spans`: the file offset and length of each <Species> element, so they
 *     can be parsed and released one at a time.
 *
 * Returns false if the file cannot be read or no <ListOfSpecies> element is
 * present, in which case the caller should fall back to the DOM path.
 */
bool splitSpeciesStream(const std::string &filename,
		std::string &skeleton,
		std::vector<SpeciesSpan> &spans);

/*! Same pass, but elides two containers at once.
 *
 * <ListOfSpecies> dominates chain-encoded models (one molecule element per
 * monomer of the seed polymer); <ListOfReactionRules> dominates indexed
 * models (one rule per site).  Both are parsed by the existing code as an
 * independent loop over child elements, so both can be streamed. */
bool splitStreamedSections(const std::string &filename,
		std::string &skeleton,
		std::vector<SpeciesSpan> &speciesSpans,
		std::vector<SpeciesSpan> &ruleSpans);

/*! Read one recorded span back out of the file as a standalone XML fragment. */
bool readSpeciesSpan(std::FILE *handle, const SpeciesSpan &span,
		std::string &fragment);

}

#endif
