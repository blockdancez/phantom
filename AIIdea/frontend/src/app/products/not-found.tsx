// frontend/src/app/products/not-found.tsx
export default function ProductNotFound() {
  return (
    <div data-testid="product-not-found" className="text-center py-20">
      <h1 className="text-xl font-medium">没找到这份产品体验报告</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        可能这份 ID 无效，或者它已经被清理。
      </p>
    </div>
  );
}
