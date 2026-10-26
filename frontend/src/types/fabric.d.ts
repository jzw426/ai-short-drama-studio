// fabric@5 的 dist 构建未附带 .d.ts，这里声明其命名导出为 any
// （编辑器实现中已对 fabric 对象显式标注类型，保持画布逻辑的灵活性）
declare module "fabric" {
  export const Canvas: any;
  export const IText: any;
  export const Text: any;
  export const Rect: any;
  export const Group: any;
  export const Line: any;
  export const Circle: any;
  export const Polyline: any;
  export const Image: any;
  export const Point: any;
  export const Object: any;
  export const util: any;
}
