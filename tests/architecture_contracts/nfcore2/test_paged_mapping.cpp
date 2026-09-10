#include "test_harness.hh"
#include "NFcore.hh"

TEST(PagedMapping_EmptyAndBounds)
{
	NFcore::PagedMappingIdTable table;
	EXPECT_EQ(table.ensure(0), static_cast<NFcore::MappingIdSet *>(0));
	EXPECT_EQ(table.get(0), static_cast<const NFcore::MappingIdSet *>(0));

	table.init(65);
	EXPECT_EQ(table.get(0), static_cast<const NFcore::MappingIdSet *>(0));
	EXPECT_EQ(table.get(64), static_cast<const NFcore::MappingIdSet *>(0));
	EXPECT_EQ(table.get(65), static_cast<const NFcore::MappingIdSet *>(0));
	EXPECT_EQ(table.ensure(65), static_cast<NFcore::MappingIdSet *>(0));
}

TEST(PagedMapping_PagesReleaseOnlyWhenEmpty)
{
	NFcore::PagedMappingIdTable table;
	table.init(65);

	NFcore::MappingIdSet *first = table.ensure(0);
	EXPECT_TRUE(first != 0);
	EXPECT_TRUE(first->empty());
	EXPECT_TRUE(first->insert(17).second);
	table.noteBecameNonempty(0);
	EXPECT_EQ(table.get(0), first);
	EXPECT_TRUE(table.get(1) != 0); // same allocated page

	NFcore::MappingIdSet *samePage = table.ensure(31);
	EXPECT_TRUE(samePage != 0);
	EXPECT_TRUE(samePage->insert(31).second);
	table.noteBecameNonempty(31);
	NFcore::MappingIdSet *nextPage = table.ensure(32);
	EXPECT_TRUE(nextPage != 0);
	EXPECT_TRUE(nextPage->insert(32).second);
	table.noteBecameNonempty(32);

	first->clear();
	table.noteBecameEmpty(0);
	EXPECT_TRUE(table.get(0) != 0);
	EXPECT_TRUE(table.get(0)->empty());
	EXPECT_EQ(table.get(31), samePage);
	EXPECT_EQ(table.get(32), nextPage);

	samePage->clear();
	table.noteBecameEmpty(31);
	EXPECT_EQ(table.get(31), static_cast<const NFcore::MappingIdSet *>(0));
	EXPECT_EQ(table.get(32), nextPage);

	nextPage->clear();
	table.noteBecameEmpty(32);
	EXPECT_EQ(table.get(32), static_cast<const NFcore::MappingIdSet *>(0));
}

TEST(PagedMapping_ReinitializeClearsAndReuses)
{
	NFcore::PagedMappingIdTable table;
	table.init(1);
	NFcore::MappingIdSet *reused = table.ensure(0);
	EXPECT_TRUE(reused != 0);
	EXPECT_TRUE(reused->empty());
	EXPECT_TRUE(reused->insert(4).second);
	table.noteBecameNonempty(0);
	table.init(0);
	EXPECT_EQ(table.ensure(0), static_cast<NFcore::MappingIdSet *>(0));
}
