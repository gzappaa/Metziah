import httpx


class LaibcatalogClient:

    BASE_URL = "https://laibcatalog.co.il"


    def __init__(self, chain_id):
        self.chain_id = chain_id


    async def get_files(self, branch_number=None):

        params = {
            "edi": self.chain_id
        }

        if branch_number:
            params["branchNumber"] = branch_number


        async with httpx.AsyncClient() as client:

            response = await client.get(
                f"{self.BASE_URL}/webapi/api/getfiles",
                params=params
            )

            response.raise_for_status()

            return response.json()



    def build_download_url(self, filename):

        return (
            f"{self.BASE_URL}"
            f"/webapi/{self.chain_id}/{filename}"
        )


    async def download_file(self, url):

        async with httpx.AsyncClient() as client:

            response = await client.get(url)

            response.raise_for_status()

            return response.content