/*
 * fixedPointSelector.cpp
 *
 * Direct-method reaction selection with 64-bit fixed-point propensities
 * (the arithmetic used by ezgillespz).  Opt-in with NFSIM_FIXED_POINT=1.
 *
 * Every propensity a_r is held as q_r = round(a_r * 2^S).  The total and the
 * per-block sums are exact integer sums, so incremental updates never drift
 * and an update that leaves q_r unchanged is skipped outright.  A reaction is
 * chosen with one 64-bit random word z as the integer floor(z * total / 2^64)
 * compared against exact integer running sums.  The only rounding is the
 * quantization of each propensity, relative error at most 2^-(S+1) / a_r.
 *
 * S is chosen so the total stays below 2^60 with headroom; if a later total
 * would leave that range, all propensities are re-quantized with a smaller S
 * (a "rescale").  Trajectories differ from the double-precision
 * DirectSelector, which remains the default.
 */
#include "reactionSelector.hh"
#include <cmath>
#include <cstdint>

using namespace NFcore;

namespace {
/* High 64 bits of a*b.  Split into 32-bit limbs rather than using __int128,
 * which MSVC does not provide.  With a = a1*2^32 + a0 and b likewise, the
 * product's bits 32..127 are p11, (p01>>32), (p10>>32) and the carry out of
 * the low limb column. */
inline std::uint64_t mulhi64(std::uint64_t a, std::uint64_t b)
{
	const std::uint64_t mask32 = 0xFFFFFFFFULL;
	const std::uint64_t a0 = a & mask32, a1 = a >> 32;
	const std::uint64_t b0 = b & mask32, b1 = b >> 32;
	const std::uint64_t p00 = a0 * b0;
	const std::uint64_t p01 = a0 * b1;
	const std::uint64_t p10 = a1 * b0;
	const std::uint64_t p11 = a1 * b1;
	const std::uint64_t lowColumn = (p00 >> 32) + (p01 & mask32) + (p10 & mask32);
	return p11 + (p01 >> 32) + (p10 >> 32) + (lowColumn >> 32);
}
}

FixedPointSelector::FixedPointSelector(vector <ReactionClass *> &rxns, System *sys)
	: ReactionSelector(sys), total(0), scaleBits(0), scale(1.0), invScale(1.0),
	  rescales(0), skippedUpdates(0)
{
	n_reactions = static_cast<int>(rxns.size());
	reactionClassList = new ReactionClass *[n_reactions > 0 ? n_reactions : 1];
	for (int r = 0; r < n_reactions; ++r) reactionClassList[r] = rxns.at(r);
	quantized.assign(static_cast<std::size_t>(n_reactions), 0);
	blockSize = 128;
	blockSums.assign((static_cast<std::size_t>(n_reactions) + blockSize - 1) / blockSize + 1, 0);
	chooseScale(0.0);
	refactorPropensities();
}

FixedPointSelector::~FixedPointSelector()
{
	delete [] reactionClassList;
}

bool FixedPointSelector::supports(const vector <ReactionClass *> &rxns)
{
	for (std::size_t r = 0; r < rxns.size(); ++r)
		if (rxns[r]->supportsCompactPartnerPoolScale())
			return false;
	return true;
}

void FixedPointSelector::chooseScale(double atotEstimate)
{
	/* Keep the total below 2^60 with at least 8 bits of headroom above the
	 * largest total seen so far, and use at most 2^52 units per unit of
	 * propensity when the system is empty. */
	int bits = 52;
	if (atotEstimate > 0.0 && std::isfinite(atotEstimate)) {
		int e = 0;
		std::frexp(atotEstimate, &e);          /* atot < 2^e */
		bits = 60 - 8 - e;
		if (bits > 52) bits = 52;
		if (bits < -60) bits = -60;
	}
	scaleBits = bits;
	scale = std::ldexp(1.0, bits);
	invScale = std::ldexp(1.0, -bits);
}

std::uint64_t FixedPointSelector::quantize(double a) const
{
	if (!(a > 0.0)) return 0;
	double q = std::nearbyint(a * scale);
	if (q < 1.0) q = 1.0;  /* never lose a nonzero channel entirely */
	return static_cast<std::uint64_t>(q);
}

void FixedPointSelector::rebuildSums()
{
	total = 0;
	std::fill(blockSums.begin(), blockSums.end(), 0);
	for (int r = 0; r < n_reactions; ++r) {
		total += quantized[static_cast<std::size_t>(r)];
		blockSums[static_cast<std::size_t>(r) / blockSize] += quantized[static_cast<std::size_t>(r)];
	}
}

double FixedPointSelector::refactorPropensities()
{
	/* Recompute every propensity, as DirectSelector::refactorPropensities does. */
	double atot = 0.0;
	for (int r = 0; r < n_reactions; ++r) atot += reactionClassList[r]->update_a();
	chooseScale(atot);
	for (int r = 0; r < n_reactions; ++r)
		quantized[static_cast<std::size_t>(r)] = quantize(reactionClassList[r]->get_a());
	rebuildSums();
	return getAtot();
}

void FixedPointSelector::setQuantized(int reaction, double newA)
{
	std::uint64_t &slot = quantized[static_cast<std::size_t>(reaction)];
	/* Rescale before this channel or the total could leave the 2^60 range
	 * (checked in floating point first, so quantize() never overflows). */
	const double limit = std::ldexp(1.0, 60);
	const double scaled = newA > 0.0 ? newA * scale : 0.0;
	const bool outOfRange = !(scaled < limit) ||
			static_cast<double>(total - slot) + scaled >= limit;
	std::uint64_t q = outOfRange ? 0 : quantize(newA);
	if (!outOfRange && q == slot) { ++skippedUpdates; return; }
	if (outOfRange) {
		++rescales;
		double atot = 0.0;
		for (int r = 0; r < n_reactions; ++r)
			atot += (r == reaction) ? newA : reactionClassList[r]->get_a();
		chooseScale(atot);
		for (int r = 0; r < n_reactions; ++r)
			quantized[static_cast<std::size_t>(r)] = quantize(
					(r == reaction) ? newA : reactionClassList[r]->get_a());
		rebuildSums();
		return;
	}
	std::size_t block = static_cast<std::size_t>(reaction) / blockSize;
	total = total - slot + q;
	blockSums[block] = blockSums[block] - slot + q;
	slot = q;
}

int FixedPointSelector::indexOf(ReactionClass *r) const
{
	int reaction = r->getRxnId();
	if (reaction >= 0 && reaction < n_reactions && reactionClassList[reaction] == r)
		return reaction;
	for (int i = 0; i < n_reactions; ++i)
		if (reactionClassList[i] == r) return i;
	return -1;
}

double FixedPointSelector::update(ReactionClass *r, double oldA, double newA)
{
	(void)oldA;
	if (r == 0) return getAtot();
	int reaction = indexOf(r);
	if (reaction >= 0) setQuantized(reaction, newA);
	return getAtot();
}

double FixedPointSelector::updateBatch(vector<ReactionClass *> &rxns)
{
	for (std::size_t i = 0; i < rxns.size(); ++i) {
		if (rxns[i] == 0) continue;
		int reaction = indexOf(rxns[i]);
		if (reaction >= 0) setQuantized(reaction, rxns[i]->get_a());
	}
	return getAtot();
}

double FixedPointSelector::updateBatch(vector<ReactionClass *> &rxns,
		const vector<double> &oldAs)
{
	(void)oldAs;
	return updateBatch(rxns);
}

double FixedPointSelector::getAtot()
{
	return static_cast<double>(total) * invScale;
}

double FixedPointSelector::getNextReactionClass(ReactionClass *&rc)
{
	rc = 0;
	if (total == 0) return -1;
	NfsimRNG &rng = sys_->getRNG();
	std::uint64_t z = (static_cast<std::uint64_t>(rng.rand_int32()) << 32) |
			static_cast<std::uint64_t>(rng.rand_int32() & 0xFFFFFFFFUL);
	std::uint64_t target = mulhi64(z, total);   /* uniform in [0, total) */
	std::uint64_t acc = 0;
	for (std::size_t block = 0; block < blockSums.size(); ++block) {
		if (target >= acc + blockSums[block]) { acc += blockSums[block]; continue; }
		std::size_t first = block * blockSize;
		std::size_t last = std::min<std::size_t>(first + blockSize,
				static_cast<std::size_t>(n_reactions));
		for (std::size_t r = first; r < last; ++r) {
			std::uint64_t q = quantized[r];
			if (target < acc + q) {
				rc = reactionClassList[r];
				/* Residual within the chosen channel, in propensity units,
				 * scaled onto the channel's actual (unquantized) propensity. */
				double fraction = (static_cast<double>(target - acc) + 0.5) /
						static_cast<double>(q);
				return fraction * rc->get_a();
			}
			acc += q;
		}
	}
	return -1;
}
